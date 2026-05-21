"""PurpleAir HTTP client and rate-limiting helpers.

Provides an APIClient wrapper around httpx.Client that honors
rate limits stored in the DB and handles 429/Retry-After.
Requires PURPLEAIR_API_KEY to be present in the environment.
"""
from __future__ import annotations

from typing import Optional, Iterator, Any, Type
from contextlib import contextmanager
import logging
from email.utils import parsedate_to_datetime
import time
import os

import httpx                                                                
from pydantic import TypeAdapter                                                                   




class APIClient:
    def __init__(self, client: httpx.Client, max_retries: int = 4, default_headers: Optional[dict] = None):
        self._client = client
        self._max_retries = max_retries
        self._default_headers = default_headers or {}
        self.http_429s = 0
        self.http_429_sleep_seconds = 0.0

    def get(self, url: str, **kwargs) -> httpx.Response:
        headers = dict(self._default_headers)
        if kwargs.get("headers"):
            headers.update(kwargs["headers"])
        kwargs["headers"] = headers
        backoff = 1
        for _attempt in range(1, self._max_retries + 1):
            resp = self._client.get(url, **kwargs)
                                         
            try:
                logging.getLogger("purpleair").debug("PurpleAir response headers: %s", dict(resp.headers))
            except Exception:
                pass
            if resp.status_code == 429:
                                                                                              
                wait_seconds = None
                ra = resp.headers.get("Retry-After")
                if ra:
                                                               
                    try:
                        if ra.isdigit():
                            wait_seconds = int(ra)
                        else:
                            dt = parsedate_to_datetime(ra)
                            wait_seconds = max(0, int(dt.timestamp() - time.time()))
                    except Exception:
                        wait_seconds = None
                if wait_seconds is None:
                                               
                    for h in ("X-RateLimit-Reset", "RateLimit-Reset", "X-RateLimit-ResetUtc"):
                        v = resp.headers.get(h)
                        if not v:
                            continue
                        try:
                                                                          
                            if v.isdigit():
                                reset_ts = int(v)
                            else:
                                try:
                                    reset_ts = int(float(v))
                                except Exception:
                                    dt = parsedate_to_datetime(v)
                                    reset_ts = int(dt.timestamp())
                            wait_seconds = max(0, int(reset_ts - time.time()))
                            break
                        except Exception:
                            wait_seconds = None
                                                                                 
                if wait_seconds is None:
                    wait_seconds = backoff

                                          
                self.http_429s += 1
                self.http_429_sleep_seconds += float(wait_seconds)
                logging.getLogger("purpleair").warning(
                    "Received 429 from PurpleAir; sleeping %s seconds (attempt %d/%d). Headers: %s",
                    wait_seconds,
                    _attempt,
                    self._max_retries,
                    dict(resp.headers),
                )
                time.sleep(wait_seconds)
                backoff = min(backoff * 2, 300)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def get_metrics(self) -> dict:
        return {
            "rate_limit": None,
            "http_429": {"count": self.http_429s, "sleep_seconds": self.http_429_sleep_seconds},
        }





@contextmanager
def get_api_client(name: str = "PurpleAir") -> Iterator[APIClient]:
                                                                             
    api_key = None
    try:
        import sources.openaq.importer as openaq_importer                
        api_key = openaq_importer._get_api_key_for_external_api(name)
    except Exception:
        api_key = None
    if not api_key:
        api_key = os.getenv("PURPLEAIR_API_KEY")
    if not api_key:
        raise RuntimeError("PURPLEAIR_API_KEY is required for PurpleAir ingestion")
    headers = {"X-API-Key": api_key}
    with httpx.Client(timeout=30.0) as raw_client:
        yield APIClient(raw_client, default_headers=headers)


def fetch_json(client: APIClient, url: str, params: dict | None = None, headers: dict | None = None, schema: Optional[Type[Any]] = None) -> Any | None:
    try:
        resp = client.get(url, params=params, headers=headers)
        data = resp.json()
        if schema is not None:
            try:
                ta = TypeAdapter(schema)
                return ta.validate_python(data)
            except Exception:
                return None
        return data
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            body = ""
        body_msg = f" Body: {body.strip()[:500]}" if body else ""
        print(f"PurpleAir fetch failed: {e}{body_msg}")
        return None
    except Exception as e:
        print(f"PurpleAir fetch failed: {e}")
        return None
