from __future__ import annotations

"""Verify Philippine review inputs without provider or credential access."""

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .source_facts import sha256_file
except ImportError:  # Direct script execution keeps the tools usable without installation.
    from source_facts import sha256_file


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_ROOT = (
    REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "reference_data"
)
DEFAULT_CANDIDATE = (
    REFERENCE_ROOT
    / "provenance"
    / "philippines_denr"
    / "candidate.json"
)
EXPECTED_HASHES = {
    "candidate": "afa6b290d6de675a29149f7d75d33edc4ff75ec3004ac78895f6d35c133618e0",
    "openaq_measurements": (
        "dd93fda403acb4ad59e6819977c3e157c36203e12447617345fc0edd5c9d8ed3"
    ),
    "purpleair_measurements": (
        "aba35bb8e380a2e3343af724fa565b849f717f3783b006d9512405af3cd55028"
    ),
    "phase2i5_openaq_approved": (
        "429e3242f807134204d71cd2cb0ddf81f6587f358a27cc035a4034542e6e3f52"
    ),
    "phase2i5_purpleair_approved": (
        "2499ba09275d191cc341be3d2283bc59915fed77d49c48e40cb2a0432a717b82"
    ),
}

def verify_integrity(candidate_path: Path = DEFAULT_CANDIDATE) -> dict[str, Any]:
    paths = {
        "candidate": candidate_path,
        "openaq_measurements": (
            REFERENCE_ROOT / "public" / "openaq" / "measurements.jsonl"
        ),
        "purpleair_measurements": (
            REFERENCE_ROOT / "restricted" / "purpleair" / "measurements.jsonl"
        ),
        "phase2i5_openaq_approved": (
            REFERENCE_ROOT
            / "expected"
            / "public"
            / "openaq"
            / "phase2i5-approved.json"
        ),
        "phase2i5_purpleair_approved": (
            REFERENCE_ROOT
            / "expected"
            / "restricted"
            / "purpleair"
            / "phase2i5-approved.json"
        ),
    }
    actual_hashes = {name: sha256_file(path) for name, path in paths.items()}
    changed = {
        name: {"expected": EXPECTED_HASHES[name], "actual": actual_hashes[name]}
        for name in paths
        if actual_hashes[name] != EXPECTED_HASHES[name]
    }
    if changed:
        raise ValueError(f"Frozen Philippine review input changed: {changed}")

    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    referenced_hashes = candidate.get("source_hashes", {})
    if referenced_hashes != {
        "openaq_measurements_sha256": actual_hashes["openaq_measurements"],
        "purpleair_measurements_sha256": actual_hashes["purpleair_measurements"],
    }:
        raise ValueError("Candidate source hashes do not match frozen measurements")
    if candidate.get("provider_calls") != 0:
        raise ValueError("Candidate does not record zero provider calls")

    return {
        "schema_version": "philippines-denr-integrity-1",
        "artifact_kind": "integrity_verification",
        "status": "verified",
        "hashes": actual_hashes,
        "candidate_case_count": len(candidate.get("cases", [])),
        "safety": {
            "provider_calls": 0,
            "credential_reads": 0,
            "purpleair_points_consumed": 0,
            "paid_imports_enabled": False,
        },
        "phase2i5_approved_expectations_unchanged": True,
        "frozen_measurements_unchanged": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = verify_integrity(args.candidate.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
