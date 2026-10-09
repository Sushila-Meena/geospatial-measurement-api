"""Reading KML and Shapefile data into GeoDataFrames."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pyogrio
from pyproj import CRS

from app.services.errors import GeoProcessingError


@dataclass
class LayerData:
    name: Optional[str]
    gdf: gpd.GeoDataFrame
    drop_empty_properties: bool = False  # KML adds many empty standard fields


def parse_crs(value: str) -> CRS:
    """Parse a user-supplied CRS such as 'EPSG:4326'. Raises ValueError if invalid."""
    return CRS.from_user_input(value)


def read_kml(path: Path) -> list[LayerData]:
    """Read every layer (KML <Folder>) of a KML file. KML coordinates are always WGS 84."""
    try:
        layer_names = [str(row[0]) for row in pyogrio.list_layers(path)]
        layers = []
        for name in layer_names:
            gdf = gpd.read_file(path, layer=name)
            if gdf.crs is None:
                gdf = gdf.set_crs(4326)  # the KML specification defines WGS 84
            layers.append(LayerData(name, gdf, drop_empty_properties=True))
        return layers
    except Exception as exc:
        raise GeoProcessingError(f"Could not read the KML file: {exc}") from exc


def read_shapefile(path: Path, assume_crs: Optional[CRS]) -> LayerData:
    """Read one Shapefile. A missing .prj (no CRS) is an error unless assume_crs is given."""
    try:
        gdf = gpd.read_file(path)
    except Exception as exc:
        raise GeoProcessingError(f"Could not read the Shapefile '{path.name}': {exc}") from exc
    if gdf.crs is None:
        if assume_crs is None:
            raise GeoProcessingError(
                f"Shapefile '{path.name}' has no CRS (missing .prj file). "
                "Add the .prj file, or re-upload with the 'assume_crs' field, e.g. EPSG:4326."
            )
        gdf = gdf.set_crs(assume_crs)
    return LayerData(path.stem, gdf)
