from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from services.csv_measurement_import import (
    import_measurements_csv_text,
    require_csv_upload_api_key,
    validate_csv_upload_file,
)


router = APIRouter(prefix="/ingest", tags=["programmatic-imports"])


@router.post("/upload-csv", dependencies=[Depends(require_csv_upload_api_key)])
async def upload_csv_measurements_programmatic(file: UploadFile = File(...)):
    """
    Programmatic CSV ingest using API key authentication.
    Required header columns: internalsensorid, datetime, value
    """
    upload = await validate_csv_upload_file(file)
    return import_measurements_csv_text(upload.text)
