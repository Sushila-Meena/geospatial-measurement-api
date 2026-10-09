"""Unit tests for measure_geometry (no HTTP, no database)."""
import pytest
from pyproj import CRS
from shapely.geometry import (
    GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon,
)

from app.services.measurements import ERROR, NOT_APPLICABLE, OK, UNSUPPORTED, measure_geometry
from tests.conftest import SQUARE, SQUARE_GEODESIC_AREA

WGS84 = CRS.from_epsg(4326)


def test_polygon_area_matches_geodesic_reference():
    result = measure_geometry(SQUARE, WGS84)
    assert result.status == OK
    assert result.values["projected_crs"] == "EPSG:32643"
    # UTM and ellipsoidal area agree within 0.1 %
    assert result.values["area_m2"] == pytest.approx(SQUARE_GEODESIC_AREA, rel=1e-3)
    assert result.values["geodesic_area_m2"] == pytest.approx(SQUARE_GEODESIC_AREA, rel=1e-6)


def test_area_is_not_computed_in_degrees():
    result = measure_geometry(SQUARE, WGS84)
    assert SQUARE.area == pytest.approx(0.0001)           # the wrong, degree-based number
    assert result.values["area_m2"] > 1_000_000            # real square metres


def test_line_length():
    line = LineString([(75.80, 26.90), (75.81, 26.90)])    # 0.01 deg of longitude at 26.9 N
    result = measure_geometry(line, WGS84)
    assert result.status == OK
    assert result.values["length_m"] == pytest.approx(result.values["geodesic_length_m"], rel=1e-3)
    assert 990 < result.values["length_m"] < 1000          # about 993 m


def test_multipolygon_sums_parts():
    other = Polygon([(75.90, 26.90), (75.91, 26.90), (75.91, 26.91), (75.90, 26.91)])
    result = measure_geometry(MultiPolygon([SQUARE, other]), WGS84)
    single = measure_geometry(SQUARE, WGS84).values["area_m2"]
    assert result.values["area_m2"] == pytest.approx(2 * single, rel=1e-3)


def test_multilinestring_sums_parts():
    a = LineString([(75.80, 26.90), (75.81, 26.90)])
    b = LineString([(75.90, 26.90), (75.91, 26.90)])
    result = measure_geometry(MultiLineString([a, b]), WGS84)
    one = measure_geometry(a, WGS84).values["length_m"]
    assert result.values["length_m"] == pytest.approx(2 * one, rel=1e-3)


def test_hole_is_subtracted_in_both_methods():
    outer = [(75.80, 26.90), (75.81, 26.90), (75.81, 26.91), (75.80, 26.91)]
    hole = [(75.803, 26.903), (75.807, 26.903), (75.807, 26.907), (75.803, 26.907)]
    result = measure_geometry(Polygon(outer, [hole]), WGS84)
    full = measure_geometry(Polygon(outer), WGS84).values
    hole_only = measure_geometry(Polygon(hole), WGS84).values
    assert result.values["area_m2"] == pytest.approx(full["area_m2"] - hole_only["area_m2"], rel=1e-6)
    assert result.values["geodesic_area_m2"] == pytest.approx(
        full["geodesic_area_m2"] - hole_only["geodesic_area_m2"], rel=1e-6
    )


def test_points_are_not_applicable():
    for geom in (Point(75.8, 26.9), MultiPoint([(75.8, 26.9), (75.9, 26.9)])):
        result = measure_geometry(geom, WGS84)
        assert result.status == NOT_APPLICABLE
        assert result.values is None


def test_unsupported_and_empty_geometries_do_not_crash():
    collection = GeometryCollection([Point(75.8, 26.9), SQUARE])
    assert measure_geometry(collection, WGS84).status == UNSUPPORTED
    assert measure_geometry(Polygon(), WGS84).status == UNSUPPORTED
    assert measure_geometry(None, WGS84).status == UNSUPPORTED


def test_invalid_bowtie_polygon_is_repaired_with_warning():
    bowtie = Polygon([(75.80, 26.90), (75.81, 26.91), (75.81, 26.90), (75.80, 26.91)])
    assert not bowtie.is_valid
    result = measure_geometry(bowtie, WGS84)
    assert result.status == OK
    assert "repaired" in result.message
    assert result.values["area_m2"] > 0


def test_z_coordinates_are_ignored():
    with_z = Polygon([(75.80, 26.90, 100), (75.81, 26.90, 200), (75.81, 26.91, 300), (75.80, 26.91, 400)])
    assert measure_geometry(with_z, WGS84).values["area_m2"] == pytest.approx(
        measure_geometry(SQUARE, WGS84).values["area_m2"], rel=1e-9
    )


def test_projected_source_crs_is_handled():
    """A square given in UTM 43N metres must come back with the same area."""
    utm = CRS.from_epsg(32643)
    square = Polygon([(713000, 2976000), (714000, 2976000), (714000, 2977000), (713000, 2977000)])
    result = measure_geometry(square, utm)
    assert result.values["area_m2"] == pytest.approx(1_000_000, rel=1e-6)


def test_web_mercator_input_is_not_trusted_for_area():
    """EPSG:3857 inflates areas at high latitude; we must still return the real area."""
    from pyproj import Transformer

    to_3857 = Transformer.from_crs(4326, 3857, always_xy=True).transform
    from shapely.ops import transform

    mercator_square = transform(to_3857, SQUARE)
    assert mercator_square.area > 1_300_000                 # naive area in Mercator is inflated (~1.24x)
    result = measure_geometry(mercator_square, CRS.from_epsg(3857))
    assert result.values["area_m2"] == pytest.approx(SQUARE_GEODESIC_AREA, rel=1e-3)


def test_wrong_crs_gives_error_not_crash():
    """Degree-sized numbers declared as UTM metres end up at a valid but meaningless place;
    numbers far outside the CRS's valid range must be reported, never raise."""
    huge = Polygon([(1e9, 1e9), (1e9 + 1, 1e9), (1e9 + 1, 1e9 + 1)])
    result = measure_geometry(huge, CRS.from_epsg(32643))
    assert result.status == ERROR
