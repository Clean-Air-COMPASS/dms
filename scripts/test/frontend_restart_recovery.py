"""Exercise the built frontend against a real, disposable Compose application.

Uses only Python's standard library and Docker CLI on Windows or Linux. The
caller must provision a dedicated project, unique container names, loopback web
port and project-owned volumes/network. See docs/operations.md for invocation.
Never run this against an installation whose availability must be preserved.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def wait_until(predicate, timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise AssertionError(f"Recovery condition not met within {timeout} seconds")


class FrontendRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docker = ["docker", "--context", options.context]
        cls.compose = cls.docker + ["compose", "-p", options.project]
        if options.env_file:
            cls.compose += ["--env-file", options.env_file]
        for path in options.file:
            cls.compose += ["-f", path]
        config = json.loads(command(*cls.compose, "config", "--format", "json"))
        if not options.project.startswith("compassaq-restart-"):
            raise ValueError("Use a dedicated compassaq-restart-* project")
        cls.network = config["networks"]["default"]["name"]
        if not cls.network.startswith(options.project + "_"):
            raise ValueError("Network must belong to the test project")
        for volume in config.get("volumes", {}).values():
            if volume.get("external") or not volume["name"].startswith(options.project + "_"):
                raise ValueError("All volumes must belong to the test project")
        cls.containers = {}
        for service in ("frontend", "api", "db", "scheduler"):
            ids = command(*cls.compose, "ps", "-aq", service).split()
            if len(ids) != 1:
                raise ValueError(f"Expected one existing {service} container")
            container = json.loads(command(*cls.docker, "inspect", ids[0]))[0]
            labels = container["Config"]["Labels"]
            if labels.get("com.docker.compose.project") != options.project:
                raise ValueError("Container ownership mismatch")
            if not container["Name"].startswith("/" + options.project + "-"):
                raise ValueError("Container name must belong to the test project")
            if set(container["NetworkSettings"]["Networks"]) != {cls.network}:
                raise ValueError("Containers must use only the test network")
            for mount in container["Mounts"]:
                if mount["Type"] != "volume" or not mount["Name"].startswith(options.project + "_"):
                    raise ValueError("Unexpected or shared container mount")
            cls.containers[service] = ids[0]
        frontend = cls.inspect("frontend")
        ports = frontend["NetworkSettings"]["Ports"]["80/tcp"]
        target = urlsplit(options.base_url)
        if (target.scheme != "http" or target.hostname != "127.0.0.1"
                or len(ports) != 1 or ports[0]["HostIp"] != "127.0.0.1"
                or int(ports[0]["HostPort"]) != target.port):
            raise ValueError("URL must match the isolated loopback frontend port")

    @classmethod
    def inspect(cls, service):
        return json.loads(command(*cls.docker, "inspect", cls.containers[service]))[0]

    @classmethod
    def fetch(cls, path):
        try:
            with urlopen(options.base_url.rstrip("/") + path, timeout=3) as response:
                return response.status, response.read().decode()
        except HTTPError as error:
            return error.code, error.read().decode()
        except (URLError, TimeoutError):
            return 0, ""

    @classmethod
    def ready(cls):
        status, body = cls.fetch("/")
        api_status, api_body = cls.fetch("/api/health/readiness")
        return (status == 200 and '<div id="root">' in body
                and api_status == 200 and json.loads(api_body) == {"status": "ready"}
                and cls.inspect("frontend")["State"]["Health"]["Status"] == "healthy")

    def test_01_application_is_ready(self):
        wait_until(self.ready)

    def test_02_api_address_change_without_frontend_restart(self):
        frontend_before = self.inspect("frontend")
        api_before = self.inspect("api")
        previous_ip = api_before["NetworkSettings"]["Networks"][self.network]["IPAddress"]
        scheduler_ip = self.inspect("scheduler")["NetworkSettings"]["Networks"][self.network]["IPAddress"]
        # Swap allocation order, reproducing the API/scheduler address exchange
        # observed in NEW-002 without relying on a host-specific restart race.
        order = (["scheduler", "api"] if ipaddress.ip_address(previous_ip)
                 < ipaddress.ip_address(scheduler_ip) else ["api", "scheduler"])
        try:
            for service in ("api", "scheduler"):
                command(*self.docker, "network", "disconnect", self.network, self.containers[service])
            for service in order:
                command(*self.docker, "network", "connect", "--alias", service,
                        self.network, self.containers[service])
        finally:
            for service in ("api", "scheduler"):
                if self.network not in self.inspect(service)["NetworkSettings"]["Networks"]:
                    command(*self.docker, "network", "connect", "--alias", service,
                            self.network, self.containers[service])
        replacement = self.inspect("api")["NetworkSettings"]["Networks"][self.network]["IPAddress"]
        self.assertNotEqual(previous_ip, replacement)
        wait_until(self.ready)
        self.assertEqual(frontend_before["State"]["StartedAt"],
                         self.inspect("frontend")["State"]["StartedAt"])
        print(f"API address changed {previous_ip} -> {replacement}; frontend did not restart", flush=True)

    def test_03_frontend_starts_without_api_and_recovers(self):
        command(*self.compose, "stop", "api")
        try:
            command(*self.compose, "restart", "frontend")
            wait_until(lambda: self.inspect("frontend")["State"]["Health"]["Status"] == "unhealthy")
            self.assertEqual(self.inspect("frontend")["State"]["Status"], "running")
            self.assertEqual(self.fetch("/")[0], 200)
            self.assertNotEqual(self.fetch("/api/health/readiness")[0], 200)
            frontend_started = self.inspect("frontend")["State"]["StartedAt"]
        finally:
            command(*self.compose, "start", "api")
        wait_until(self.ready)
        self.assertEqual(frontend_started, self.inspect("frontend")["State"]["StartedAt"])

    def test_04_health_rejects_missing_application_content(self):
        command(*self.compose, "exec", "-T", "frontend", "mv",
                "/usr/share/nginx/html/index.html", "/usr/share/nginx/html/index.html.recovery-test")
        try:
            wait_until(lambda: self.inspect("frontend")["State"]["Health"]["Status"] == "unhealthy")
            self.assertEqual(self.fetch("/api/health/readiness")[0], 200)
        finally:
            command(*self.compose, "exec", "-T", "frontend", "mv",
                    "/usr/share/nginx/html/index.html.recovery-test", "/usr/share/nginx/html/index.html")
        wait_until(self.ready)

    def test_05_original_combined_application_restart(self):
        command(*self.compose, "restart", "api", "scheduler", "frontend")
        wait_until(self.ready)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="default")
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("-f", "--file", action="append", required=True)
    parser.add_argument("--base-url", required=True)
    options, test_args = parser.parse_known_args()
    unittest.main(argv=[__file__, *test_args], verbosity=2)
