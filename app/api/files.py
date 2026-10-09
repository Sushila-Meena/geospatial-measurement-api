"""HTTP endpoints for uploading files and reading results."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import Feature, FileStatus, UploadedFile
from app.services.processing import ingest_file

router = APIRouter(prefix="/api/files", tags=["files"])

ERROR_RESPONSES = {
    400: {"model": schemas.ErrorResponse, "description": "Invalid upload (bad ZIP, empty file, unsafe paths)"},
    413: {"model": schemas.ErrorResponse, "description": "File too large"},
    415: {"model": schemas.ErrorResponse, "description": "Unsupported file type"},
    422: {"model": schemas.ErrorResponse, "description": "File accepted but could not be processed (stored as FAILED)"},
}
def _get_file_or_404(db: Session, file_id: str) -> UploadedFile:
    file_id = file_id.strip()
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"File '{file_id}' not found")
    return record
@router.post(
    "/",
    response_model=schemas.FileInfo,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    summary="Upload and process a geospatial file",
)
def upload_file(
    file: UploadFile = File(..., description="A .kml file, or a .zip containing a Shapefile"),
    assume_crs: Optional[str] = Form(
        None,
        description="CRS to assume when a Shapefile has no .prj file, e.g. EPSG:4326",
    ),
    db: Session = Depends(get_db),
):
    """Upload a KML or zipped Shapefile. The file is processed before the response is returned."""
    return ingest_file(db, file.file, file.filename or "upload", assume_crs)


@router.get("/{file_id}/", response_model=schemas.FileInfo, summary="Information about an uploaded file")
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _get_file_or_404(db, file_id)


@router.get(
    "/{file_id}/measurements/",
    response_model=schemas.MeasurementsResponse,
    summary="Measurements for every feature in a file",
)
def get_measurements(
    file_id: str,
    limit: int = Query(1000, ge=1, le=5000, description="Maximum features to return"),
    offset: int = Query(0, ge=0, description="Number of features to skip"),
    include_geometry: bool = Query(True, description="Set false for a much smaller response"),
    db: Session = Depends(get_db),
):
    record = _get_file_or_404(db, file_id)
    if record.status != FileStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"File is {record.status}; measurements are only available for COMPLETED files.",
        )

    rows = db.scalars(
        select(Feature)
        .where(Feature.file_id == file_id)
        .order_by(Feature.feature_index)
        .offset(offset)
        .limit(limit)
    ).all()

    return schemas.MeasurementsResponse(
        file_id=record.id,
        filename=record.filename,
        crs=record.crs,
        feature_count=record.feature_count,
        summary=_summarise(db, file_id),
        limit=limit,
        offset=offset,
        returned=len(rows),
        features=[
            schemas.FeatureMeasurement(
                feature_id=row.feature_index,
                layer=row.layer,
                geometry_type=row.geometry_type,
                crs=row.crs,
                properties=row.properties,
                geometry=row.geometry if include_geometry else None,
                measurement_status=row.measurement_status,
                measurement=row.measurement,
                message=row.message,
            )
            for row in rows
        ],
    )


def _summarise(db: Session, file_id: str) -> schemas.MeasurementSummary:
    """Totals over ALL features of the file (not just the requested page)."""
    total_area = total_length = 0.0
    type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    query = select(Feature.geometry_type, Feature.measurement_status, Feature.measurement).where(
        Feature.file_id == file_id
    )
    for geometry_type, measurement_status, measurement in db.execute(query):
        type_counts[geometry_type] = type_counts.get(geometry_type, 0) + 1
        status_counts[measurement_status] = status_counts.get(measurement_status, 0) + 1
        if measurement:
            total_area += measurement.get("area_m2", 0.0)
            total_length += measurement.get("length_m", 0.0)
    return schemas.MeasurementSummary(
        total_area_m2=round(total_area, 4),
        total_length_m=round(total_length, 4),
        geometry_type_counts=type_counts,
        measurement_status_counts=status_counts,
    )
