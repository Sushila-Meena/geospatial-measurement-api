"""Pydantic response models (the API contract)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    size_bytes: int
    feature_count: int
    crs: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class FeatureMeasurement(BaseModel):
    feature_id: int
    layer: Optional[str] = None
    geometry_type: str
    crs: Optional[str] = None
    properties: dict[str, Any]
    geometry: Optional[dict[str, Any]] = None
    measurement_status: str
    measurement: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class MeasurementSummary(BaseModel):
    total_area_m2: float
    total_length_m: float
    geometry_type_counts: dict[str, int]
    measurement_status_counts: dict[str, int]


class MeasurementsResponse(BaseModel):
    file_id: str
    filename: str
    crs: Optional[str] = None
    feature_count: int
    summary: MeasurementSummary
    limit: int
    offset: int
    returned: int
    features: list[FeatureMeasurement]


class ErrorResponse(BaseModel):
    detail: str
    id: Optional[str] = None
    status: Optional[str] = None
