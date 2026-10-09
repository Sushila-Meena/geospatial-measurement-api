"""Unit tests for UTM zone selection."""
import pytest

from app.services.crs import utm_epsg_for


@pytest.mark.parametrize(
    "lon, lat, expected",
    [
        (75.8, 26.9, 32643),     # Jaipur, India: zone 43 north
        (77.2, 28.6, 32643),     # Delhi
        (-0.12, 51.5, 32630),    # London: zone 30 north
        (18.4, -33.9, 32734),    # Cape Town: zone 34 south
        (-74.0, 40.7, 32618),    # New York: zone 18 north
        (179.9, 10.0, 32660),    # far east edge: zone 60
        (-179.9, 10.0, 32601),   # far west edge: zone 1
        (180.0, 10.0, 32660),    # lon == 180 must not become zone 61
        (10.0, 85.0, 32661),     # Arctic: UPS north
        (10.0, -85.0, 32761),    # Antarctic: UPS south
    ],
)
def test_utm_epsg_for(lon, lat, expected):
    assert utm_epsg_for(lon, lat) == expected
