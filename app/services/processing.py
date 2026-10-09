"""File-processing flow: validate -> extract -> read -> measure -> store.

The whole flow runs synchronously inside the upload request (see README, "Design decisions").
"""
from __future__ import annotations

import json
import logging
import math
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO, Optional

import pandas as pd
import shapely
from pyproj import CRS
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Feature, FileStatus, UploadedFile, utcnow
from app.services import file_handler
from app.services.crs import crs_label
from app.services.errors import GeoProcessingError, InvalidUploadError
from app.services.geo_reader import LayerData, parse_crs, read_kml, read_shapefile
from app.services.measurements import measure_geometry

logger = logging.getLogger(__name__)


def ingest_file(
    db: Session,
    stream: BinaryIO,
    filename: str,
    assume_crs: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> UploadedFile:
    """Process an uploaded file end to end and return the stored UploadedFile.

    Raises:
        InvalidUploadError: rejected before processing (nothing is stored).
        GeoProcessingError: content could not be processed (a FAILED record is stored).
    """
    settings = settings or get_settings()
    filename = file_handler.safe_filename(filename)
    file_type = file_handler.detect_file_type(filename)

    assumed: Optional[CRS] = None
    if assume_crs:
        try:
            assumed = parse_crs(assume_crs)
        except Exception as exc:
            raise InvalidUploadError(f"'assume_crs' is not a valid CRS: {assume_crs}") from exc

    # ignore_cleanup_errors avoids Windows file-lock errors when the temp folder is removed
    with tempfile.TemporaryDirectory(prefix="geoapi_", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        upload_path = work / ("upload.kml" if file_type == file_handler.KML else "upload.zip")
        size = file_handler.save_upload(stream, upload_path, settings)

        shapefiles: list[Path] = []
        if file_type == file_handler.SHAPEFILE:
            extracted = file_handler.extract_zip_safely(upload_path, work / "extracted", settings)
            shapefiles = file_handler.find_shapefiles(extracted)

        record = UploadedFile(filename=filename, file_type=file_type, size_bytes=size, status=FileStatus.PROCESSING)
        db.add(record)
        db.commit()

        try:
            if file_type == file_handler.KML:
                layers = read_kml(upload_path)
            else:
                layers = [read_shapefile(p, assumed) for p in shapefiles]
            features = build_features(record.id, layers, settings)
        except GeoProcessingError as exc:
            _mark_failed(db, record, exc.message)
            raise GeoProcessingError(exc.message, file_id=record.id) from exc
        except Exception:
            logger.exception("Unexpected error while processing file %s", record.id)
            _mark_failed(db, record, "Unexpected error while processing the file.")
            raise

    db.add_all(features)
    record.feature_count = len(features)
    record.crs = _file_crs_label(layers)
    record.status = FileStatus.COMPLETED
    record.completed_at = utcnow()
    db.commit()
    return record


def build_features(file_id: str, layers: list[LayerData], settings: Settings) -> list[Feature]:
    """Turn GeoDataFrame rows into measured Feature rows."""
    total = sum(len(layer.gdf) for layer in layers)
    if total == 0:
        raise GeoProcessingError("The file contains no features.")
    if total > settings.max_features:
        raise GeoProcessingError(f"The file has {total} features; the limit is {settings.max_features}.")

    features: list[Feature] = []
    index = 0
    for layer in layers:
        gdf = layer.gdf
        crs = gdf.crs
        label = crs_label(crs)
        geom_col = gdf.geometry.name
        props_rows = pd.DataFrame(gdf.drop(columns=geom_col)).to_dict("records")
        for geom, props in zip(gdf.geometry, props_rows):
            result = measure_geometry(geom, crs)
            features.append(
                Feature(
                    file_id=file_id,
                    feature_index=index,
                    layer=layer.name,
                    geometry_type=geom.geom_type if geom is not None else "None",
                    crs=label,
                    geometry=_to_geojson(geom),
                    properties=_clean_properties(props, layer.drop_empty_properties),
                    measurement_status=result.status,
                    measurement=result.values,
                    message=result.message,
                )
            )
            index += 1
    return features


def _file_crs_label(layers: list[LayerData]) -> str:
    labels = {crs_label(layer.gdf.crs) for layer in layers}
    return labels.pop() if len(labels) == 1 else "MIXED"


def _mark_failed(db: Session, record: UploadedFile, message: str) -> None:
    record.status = FileStatus.FAILED
    record.error_message = message
    record.completed_at = utcnow()
    db.commit()


def _to_geojson(geom: Any) -> Optional[dict[str, Any]]:
    if geom is None or geom.is_empty:
        return None
    return json.loads(shapely.to_geojson(geom))


def _clean_value(value: Any) -> Any:
    """Convert numpy/pandas values to plain JSON-safe Python values."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):  # numpy scalar
        return _clean_value(value.item())
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


# KML fields that only control how Google Earth draws a feature, not real attributes
KML_DISPLAY_FIELDS = {
    "tessellate", "extrude", "visibility", "altitudeMode", "drawOrder", "icon",
    "timestamp", "begin", "end", "snippet",
}


def _clean_properties(props: dict[str, Any], is_kml: bool) -> dict[str, Any]:
    cleaned = {str(k): _clean_value(v) for k, v in props.items()}
    if is_kml:  # drop empty values and display-only fields to keep responses tidy
        cleaned = {k: v for k, v in cleaned.items() if v not in (None, "") and k not in KML_DISPLAY_FIELDS}
    return cleaned
