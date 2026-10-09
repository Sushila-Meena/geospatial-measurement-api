"""FastAPI application entry point.

Run with:  uvicorn app.main:app --reload
Interactive API docs:  http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import models  # noqa: F401  (registers the tables on Base.metadata)
from app.api import files
from app.database import Base, engine
from app.services.errors import GeoProcessingError, InvalidUploadError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description=(
        "Upload a KML or zipped Shapefile and get the area of polygons and the length of lines, "
        "calculated in a projected CRS (never in lat/lon degrees)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(files.router)


@app.exception_handler(InvalidUploadError)
async def invalid_upload_handler(request: Request, exc: InvalidUploadError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(GeoProcessingError)
async def geo_processing_handler(request: Request, exc: GeoProcessingError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": exc.message, "id": exc.file_id, "status": "FAILED"},
    )


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")
