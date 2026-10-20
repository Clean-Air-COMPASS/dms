from pathlib import Path
import sys


TOOLS = Path(__file__).resolve().parent / "reference_data_tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from philippines_denr_integrity import verify_integrity  # noqa: E402


def test_philippine_review_inputs_are_frozen_and_offline():
    report = verify_integrity()
    assert report["status"] == "verified"
    assert report["candidate_case_count"] == 3
    assert report["phase2i5_approved_expectations_unchanged"] is True
    assert report["frozen_measurements_unchanged"] is True
    assert report["safety"] == {
        "provider_calls": 0,
        "credential_reads": 0,
        "purpleair_points_consumed": 0,
        "paid_imports_enabled": False,
    }
