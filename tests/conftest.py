"""Shared test fixtures: an isolated in-memory database and helpers that build test files."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# 0.01 x 0.01 degree square near Jaipur. Geodesic area on WGS 84 is 1,100,686.96 m2 (verified).
SQUARE = Polygon([(75.80, 26.90), (75.81, 26.90), (75.81, 26.91), (75.80, 26.91)])
SQUARE_GEODESIC_AREA = 1_100_686.96


@pytest.fixture()
def client():
    """TestClient wired to a fresh in-memory SQLite database for every test."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def zip_shapefile(gdf: gpd.GeoDataFrame, tmp_path: Path, keep_prj: bool = True) -> bytes:
    """Write a GeoDataFrame as a Shapefile and return the zipped bytes."""
    work = tmp_path / "shp"
    work.mkdir(exist_ok=True)
    gdf.to_file(work / "data.shp", driver="ESRI Shapefile")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for part in sorted(work.glob("data.*")):
            if part.suffix == ".prj" and not keep_prj:
                continue
            zf.write(part, part.name)
    return buffer.getvalue()


def upload(client: TestClient, name: str, content: bytes, **form):
    return client.post("/api/files/", files={"file": (name, content)}, data=form)


@pytest.fixture()
def square_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"name": ["square"]}, geometry=[SQUARE], crs=4326)


@pytest.fixture()
def utm_square_gdf() -> gpd.GeoDataFrame:
    """Exactly 1000 m x 1000 m square in EPSG:32643 (UTM 43N): true area 1,000,000 m2."""
    x, y = Transformer.from_crs(4326, 32643, always_xy=True).transform(75.80, 26.90)
    x, y = round(x), round(y)
    poly = Polygon([(x, y), (x + 1000, y), (x + 1000, y + 1000), (x, y + 1000)])
    return gpd.GeoDataFrame({"name": ["utm_square"]}, geometry=[poly], crs=32643)


def kml_document(*placemarks: str, folder: str | None = None) -> bytes:
    body = "".join(placemarks)
    if folder:
        body = f"<Folder><name>{folder}</name>{body}</Folder>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + body + "</Document></kml>"
    ).encode()


def placemark(name: str, geometry_xml: str) -> str:
    return f"<Placemark><name>{name}</name>{geometry_xml}</Placemark>"


def polygon_xml(coords: list[tuple[float, float]]) -> str:
    ring = " ".join(f"{x},{y},0" for x, y in coords + [coords[0]])
    return f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon>"
