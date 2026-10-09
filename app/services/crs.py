"""CRS helpers: choosing a projected CRS and producing readable CRS labels."""
from __future__ import annotations

from pyproj import CRS

UPS_NORTH = 32661  # Universal Polar Stereographic North
UPS_SOUTH = 32761  # Universal Polar Stereographic South
WGS84 = CRS.from_epsg(4326)


def utm_epsg_for(lon: float, lat: float) -> int:
    """Return the EPSG code of the UTM zone that contains (lon, lat).

    WGS 84 / UTM north zones are EPSG:32601-32660, south zones EPSG:32701-32760.
    Beyond 84 N / 80 S, UTM is not defined, so Universal Polar Stereographic is used.
    The special Norway/Svalbard zone widenings are ignored: UTM stays valid there,
    only with slightly more distortion.
    """
    if lat >= 84:
        return UPS_NORTH
    if lat < -80:
        return UPS_SOUTH
    zone = int((lon + 180) // 6) + 1
    zone = max(1, min(60, zone))  # lon == 180 would give zone 61
    return (32600 if lat >= 0 else 32700) + zone


def crs_label(crs: CRS) -> str:
    """Short readable label such as 'EPSG:4326'; falls back to the CRS name."""
    authority = crs.to_authority(min_confidence=70)
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name or "UNKNOWN"


def is_wgs84(crs: CRS) -> bool:
    return crs.equals(WGS84, ignore_axis_order=True)
