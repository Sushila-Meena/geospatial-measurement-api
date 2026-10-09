"""Create small sample files in sample_data/ for trying the API.

Run from the project root:  python scripts/make_sample_data.py
All sample shapes are near Jaipur, India (about 75.8 E, 26.9 N).
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

OUT = Path(__file__).resolve().parent.parent / "sample_data"

PARCEL_A = Polygon([(75.800, 26.900), (75.810, 26.900), (75.810, 26.910), (75.800, 26.910)])
PARCEL_B = Polygon([(75.820, 26.900), (75.825, 26.900), (75.825, 26.904), (75.820, 26.904)])
ROAD = LineString([(75.800, 26.895), (75.810, 26.895), (75.815, 26.900)])
WELL = Point(75.805, 26.905)


def sample_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["Parcel A", "Parcel B", "Main road", "Well"], "kind": ["plot", "plot", "road", "point"]},
        geometry=[PARCEL_A, PARCEL_B, ROAD, WELL],
        crs=4326,
    )


def write_zipped_shapefile(gdf: gpd.GeoDataFrame, zip_path: Path, keep_prj: bool = True) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        shp = Path(tmp) / "data.shp"
        gdf.to_file(shp, driver="ESRI Shapefile")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for part in sorted(Path(tmp).glob("data.*")):
                if part.suffix == ".prj" and not keep_prj:
                    continue
                zf.write(part, part.name)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    gdf = sample_frame()

    # 1) KML with 2 polygons, 1 line and 1 point
    kml = OUT / "sample.kml"
    kml.unlink(missing_ok=True)
    gdf.to_file(kml, driver="KML")

    # 2) Shapefiles can hold one geometry type, so polygons and lines go in separate zips
    write_zipped_shapefile(gdf[gdf.geom_type == "Polygon"], OUT / "sample_polygons_shapefile.zip")
    write_zipped_shapefile(gdf[gdf.geom_type == "LineString"], OUT / "sample_lines_shapefile.zip")

    # 3) Same polygons in a projected CRS (UTM zone 43N, metres)
    write_zipped_shapefile(gdf[gdf.geom_type == "Polygon"].to_crs(32643), OUT / "sample_utm43_shapefile.zip")

    # 4) Shapefile WITHOUT a .prj file: the API asks for 'assume_crs'
    write_zipped_shapefile(gdf[gdf.geom_type == "Polygon"], OUT / "sample_no_prj_shapefile.zip", keep_prj=False)

    print("Created:", *sorted(p.name for p in OUT.iterdir()), sep="\n  ")


if __name__ == "__main__":
    main()
