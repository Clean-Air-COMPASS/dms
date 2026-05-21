from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File
from sqlalchemy.orm import Session

from db import get_session
from models import QCRule
from sqlalchemy import select, func

from qaqc import discovery, registry
import pathlib, re, os

                                                               
LOCAL_DIR = pathlib.Path(__file__).resolve().parents[3] / "qaqc" / "plugins_local"
VALID_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{2,48}$")

router = APIRouter(prefix="/admin", tags=["admin"]) 


@router.get("/plugins")
def list_plugins(session: Session = Depends(get_session)):
    """List currently registered plugins with basic metadata."""
    items = []
    for name, inst in registry.all_plugins().items():
        origin = "entry_point"
        file_path = None
        try:
            mod = getattr(inst, "__module__", "")
            if mod.startswith("qaqc.plugins_local."):
                origin = "local"
                candidate = LOCAL_DIR / f"{name}.py"
                if candidate.exists():
                    file_path = str(candidate)
        except Exception:
            pass
        items.append(
            {
                "name": name,
                "display_name": getattr(inst, "display_name", None),
                "long_description": getattr(inst, "long_description", None),
                "param_schema": getattr(inst, "param_schema", None),
                "version": getattr(inst, "version", None),
                "required_access": getattr(inst, "required_access", "api-only"),
                "module": getattr(inst, "__module__", None),
                "api_version": getattr(inst, "api_version", None),
                "description": getattr(inst, "description", None),
                "origin": origin,
                "file_path": file_path,
                "deletable": origin == "local" and file_path is not None,
                                                                                                       
                "rules_count": int(
                    session.scalar(
                        select(func.count()).select_from(QCRule).where(QCRule.check_code == name)
                    )
                    or 0
                ),
            }
        )
                                                                           
    rows = session.execute(select(QCRule.check_code, func.count()).group_by(QCRule.check_code)).all()
    rules_summary = {code: int(cnt) for code, cnt in rows}
    return {"plugins": items, "rules_summary": rules_summary}


@router.get("/plugins/reload")
def reload_plugins():
    """Reload plugins from entry points and local dev directory.

    Returns discovery report and the current registered plugins list.
    """
    registry.clear()
    report = discovery.load_plugins()
    registered = sorted(list(registry.all_plugins().keys()))
    return {"report": report, "registered": registered}


@router.post("/plugins/local")
def create_local_plugin(payload: dict = Body(...)):
    """Create a new local plugin skeleton file and reload plugins.

    Payload: { name: str, description?: str }
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not VALID_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid name; use lowercase alphanumerics/underscores (min 3 chars)")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    target = LOCAL_DIR / f"{name}.py"
    if target.exists():
        raise HTTPException(status_code=409, detail="Plugin file already exists")
    long_desc = str(payload.get("description") or f"Custom plugin {name}")
    skeleton = f"""from qaqc.plugin import QCPlugin\nfrom qaqc.registry import register\nfrom qaqc.types import QCDecision, QCRecord\n\nclass {name.title().replace('_','')}Plugin(QCPlugin):\n    name = \"{name}\"\n    display_name = \"{name}\"\n    long_description = \"{long_desc}\"\n    param_schema = {{}}  # add parameter schema here if needed\n\n    def apply(self, records, context):\n        out = []\n        for r in records:\n            out.append(QCDecision(\n                sensor_id=r.sensor_id,\n                parameter_id=r.parameter_id,\n                value=r.value,\n                unit_id=r.unit_id,\n                observed_at=r.observed_at,\n                is_valid=True,\n                flags=[],\n                plugin_name=self.name,\n            ))\n        return out\n\nplugin = {name.title().replace('_','')}Plugin()\nregister(plugin)\n"""
    try:
        target.write_text(skeleton, encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write plugin file: {e}")
                    
    registry.clear()
    report = discovery.load_plugins()
    return {"created": name, "file": str(target), "report": report}


@router.delete("/plugins/{name}")
def delete_plugin(name: str):
    """Remove a local plugin source file (if present) and reload plugins.

    Does not uninstall entry_point/distributed packages.
    """
    if not VALID_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid plugin name")
    target = LOCAL_DIR / f"{name}.py"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Local plugin file not found")
    try:
        os.remove(target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete plugin file: {e}")
    registry.clear()
    report = discovery.load_plugins()
    return {"deleted": name, "report": report}


@router.post("/plugins/upload")
async def upload_plugin(file: UploadFile = File(...), overwrite: bool = False):
    """Upload a plugin source file (.py) into plugins_local and reload.

    - Only accepts single-file Python modules for now.
    - Derives plugin name from filename (without extension) and validates.
    - Set overwrite=true to replace an existing file.
    """
    fname = file.filename or ""
    if not fname.lower().endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py plugin files are supported")
    base = pathlib.Path(fname).stem
    if not VALID_NAME_RE.match(base):
        raise HTTPException(status_code=400, detail="Invalid plugin name derived from filename")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    target = LOCAL_DIR / f"{base}.py"
    if target.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="Plugin file already exists; use overwrite=true")
    try:
        content = await file.read()
        with open(target, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")
    registry.clear()
    report = discovery.load_plugins()
    return {"uploaded": base, "file": str(target), "report": report}
