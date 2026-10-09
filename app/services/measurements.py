"""Measurement of a single geometry.

Measurement flow
----------------
1. Skip / classify geometries that cannot be measured (empty, points, unsupported types).
2. Repair invalid polygons (e.g. self-intersecting "bow-ties") so the area is meaningful.
3. Transform the geometry from its source CRS to WGS 84 (EPSG:4326).
4. Pick the UTM zone from the centre of the geometry's bounding box.
5. Transform to that UTM zone (units: metres) and measure with shapely.
6. Cross-check against a geodesic measurement on the WGS 84 ellipsoid (pyproj.Geod).

Area and length are NEVER computed on latitude/longitude degrees.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import shapely
from pyproj import CRS, Geod, Transformer
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union
from shapely.validation import explain_validity, make_valid

from app.services.crs import is_wgs84, utm_epsg_for

logger = logging.getLogger(__name__)

GEOD = Geod(ellps="WGS84")
POLYGONAL = {"Polygon", "MultiPolygon"}
LINEAR = {"LineString", "MultiLineString"}
POINTLIKE = {"Point", "MultiPoint"}

# Measurement status values stored on every feature
OK = "ok"
NOT_APPLICABLE = "not_applicable"
UNSUPPORTED = "unsupported"
ERROR = "error"


@dataclass
class MeasurementResult:
    status: str
    values: Optional[dict[str, Any]] = None
    message: Optional[str] = None


@lru_cache(maxsize=256)
def _transformer(src: str, dst: str) -> Transformer:
    """Cached pyproj transformer. always_xy=True keeps (x=lon, y=lat) order."""
    return Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)


def measure_geometry(geom: Optional[BaseGeometry], src_crs: CRS) -> MeasurementResult:
    """Measure one geometry. Never raises: problems are reported in the result."""
    if geom is None or geom.is_empty:
        return MeasurementResult(UNSUPPORTED, None, "Empty or missing geometry")

    gtype = geom.geom_type
    if gtype in POINTLIKE:
        return MeasurementResult(NOT_APPLICABLE, None, "No measurement is defined for point geometries")
    if gtype not in POLYGONAL | LINEAR:
        return MeasurementResult(UNSUPPORTED, None, f"Geometry type {gtype} is not supported for measurement")

    try:
        return _measure_supported(geom, gtype, src_crs)
    except Exception as exc:  # one bad feature must not break the whole file
        logger.warning("Measurement failed for a %s feature: %s", gtype, exc)
        return MeasurementResult(ERROR, None, f"Measurement failed: {exc}")


def _measure_supported(geom: BaseGeometry, gtype: str, src_crs: CRS) -> MeasurementResult:
    warnings: list[str] = []
    geom = shapely.force_2d(geom)  # measurements are planar 2D; ignore Z values

    if gtype in POLYGONAL and not geom.is_valid:
        reason = explain_validity(geom)
        geom = _repair_polygonal(geom)
        if geom is None or geom.is_empty:
            return MeasurementResult(ERROR, None, f"Invalid polygon could not be repaired ({reason})")
        warnings.append(f"Invalid polygon was repaired before measuring ({reason})")

    # 1) to WGS 84
    geom_ll = geom if is_wgs84(src_crs) else transform(_transformer(src_crs.to_wkt(), "EPSG:4326").transform, geom)
    minx, miny, maxx, maxy = geom_ll.bounds
    if not all(map(math.isfinite, (minx, miny, maxx, maxy))) or not (
        -180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90
    ):
        return MeasurementResult(
            ERROR, None, "Coordinates are outside the valid longitude/latitude range; check the file's CRS"
        )

    # 2) to the UTM zone of the geometry centre
    epsg = utm_epsg_for((minx + maxx) / 2, (miny + maxy) / 2)
    projected_crs = f"EPSG:{epsg}"
    geom_proj = transform(_transformer("EPSG:4326", projected_crs).transform, geom_ll)

    # 3) measure
    if gtype in POLYGONAL:
        area = geom_proj.area
        perimeter = geom_proj.length
        geodesic_area = _geodesic_area(geom_ll)
        values = {
            "area_m2": _round(area),
            "perimeter_m": _round(perimeter),
            "projected_crs": projected_crs,
            "geodesic_area_m2": _round(geodesic_area),
        }
        checks = (area, perimeter, geodesic_area)
    else:
        length = geom_proj.length
        geodesic_length = _geodesic_length(geom_ll)
        values = {
            "length_m": _round(length),
            "projected_crs": projected_crs,
            "geodesic_length_m": _round(geodesic_length),
        }
        checks = (length, geodesic_length)

    if not all(map(math.isfinite, checks)):
        return MeasurementResult(ERROR, None, "Measurement produced a non-finite value")
    return MeasurementResult(OK, values, "; ".join(warnings) or None)


def _round(value: float) -> float:
    return round(float(value), 4)


def _repair_polygonal(geom: BaseGeometry) -> Optional[BaseGeometry]:
    """make_valid() may return a GeometryCollection; keep only its polygonal parts."""
    fixed = make_valid(geom)
    if fixed.geom_type in POLYGONAL:
        return fixed
    parts = [g for g in getattr(fixed, "geoms", []) if g.geom_type in POLYGONAL]
    return unary_union(parts) if parts else None


def _geodesic_area(geom_ll: BaseGeometry) -> float:
    """Area on the WGS 84 ellipsoid in m2: outer ring minus holes, summed over polygons.

    pyproj returns signed areas that depend on ring orientation, so rings are measured
    one by one with abs() instead of passing a polygon with holes straight in.
    """
    polygons = list(geom_ll.geoms) if geom_ll.geom_type == "MultiPolygon" else [geom_ll]
    total = 0.0
    for poly in polygons:
        outer = abs(GEOD.geometry_area_perimeter(Polygon(poly.exterior))[0])
        holes = sum(abs(GEOD.geometry_area_perimeter(Polygon(ring))[0]) for ring in poly.interiors)
        total += outer - holes
    return total


def _geodesic_length(geom_ll: BaseGeometry) -> float:
    lines = list(geom_ll.geoms) if geom_ll.geom_type == "MultiLineString" else [geom_ll]
    return sum(GEOD.geometry_length(line) for line in lines)
