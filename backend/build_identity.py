import json
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent
PACKAGE_PATH = BACKEND_ROOT / "application-package.json"
if not PACKAGE_PATH.exists():
    PACKAGE_PATH = BACKEND_ROOT.parent / "frontend" / "package.json"

APPLICATION_VERSION = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))["version"]
METADATA_PATH = BACKEND_ROOT / "build-metadata.json"
BACKEND_BUILD = (
    json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    if METADATA_PATH.exists()
    else {"commit_sha": None, "build_time_utc": None}
)
