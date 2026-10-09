"""End-to-end API tests: upload -> info -> measurements."""
import io
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from tests.conftest import (
    SQUARE, SQUARE_GEODESIC_AREA, kml_document, placemark, polygon_xml, upload, zip_shapefile,
)


# ---------- happy paths ----------
def test_upload_kml_and_read_measurements(client):
    kml = kml_document(
        placemark("Parcel", polygon_xml(list(SQUARE.exterior.coords)[:-1])),
        placemark("Road", "<LineString><coordinates>75.80,26.90,0 75.81,26.90,0</coordinates></LineString>"),
        placemark("Well", "<Point><coordinates>75.805,26.905,0</coordinates></Point>"),
    )
    response = upload(client, "farm.kml", kml)
    assert response.status_code == 201
    info = response.json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 3
    assert info["crs"] == "EPSG:4326"
    assert info["filename"] == "farm.kml"

    # GET /api/files/{id}/
    assert client.get(f"/api/files/{info['id']}/").json()["feature_count"] == 3

    # GET /api/files/{id}/measurements/
    body = client.get(f"/api/files/{info['id']}/measurements/").json()
    by_name = {f["properties"]["Name"]: f for f in body["features"]}
    assert by_name["Parcel"]["measurement"]["area_m2"] == pytest.approx(SQUARE_GEODESIC_AREA, rel=1e-3)
    assert by_name["Parcel"]["geometry"]["type"] == "Polygon"
    assert by_name["Road"]["measurement"]["length_m"] == pytest.approx(993, abs=5)
    assert by_name["Well"]["measurement_status"] == "not_applicable"
    assert by_name["Well"]["measurement"] is None
    assert body["summary"]["geometry_type_counts"] == {"Polygon": 1, "LineString": 1, "Point": 1}
    assert body["summary"]["total_area_m2"] == pytest.approx(SQUARE_GEODESIC_AREA, rel=1e-3)


def test_upload_shapefile_zip(client, tmp_path, square_gdf):
    response = upload(client, "parcels.zip", zip_shapefile(square_gdf, tmp_path))
    assert response.status_code == 201
    info = response.json()
    assert info["crs"] == "EPSG:4326"
    body = client.get(f"/api/files/{info['id']}/measurements/").json()
    feature = body["features"][0]
    assert feature["properties"] == {"name": "square"}
    assert feature["layer"] == "data"
    assert feature["measurement"]["area_m2"] == pytest.approx(SQUARE_GEODESIC_AREA, rel=1e-3)


def test_projected_shapefile_exact_area(client, tmp_path, utm_square_gdf):
    """A 1000 m x 1000 m square in UTM 43N must measure 1,000,000 m2."""
    response = upload(client, "utm.zip", zip_shapefile(utm_square_gdf, tmp_path))
    assert response.status_code == 201
    assert response.json()["crs"] == "EPSG:32643"
    feature = client.get(f"/api/files/{response.json()['id']}/measurements/").json()["features"][0]
    assert feature["measurement"]["area_m2"] == pytest.approx(1_000_000, rel=1e-6)
    assert feature["measurement"]["projected_crs"] == "EPSG:32643"


def test_line_shapefile(client, tmp_path):
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[LineString([(75.80, 26.90), (75.81, 26.90)])], crs=4326)
    response = upload(client, "road.zip", zip_shapefile(gdf, tmp_path))
    feature = client.get(f"/api/files/{response.json()['id']}/measurements/").json()["features"][0]
    assert feature["measurement"]["length_m"] == pytest.approx(993, abs=5)


def test_kml_with_several_folders_keeps_layer_names(client):
    folder_a = "<Folder><name>Plots</name>" + placemark("P1", polygon_xml(list(SQUARE.exterior.coords)[:-1])) + "</Folder>"
    folder_b = "<Folder><name>Wells</name>" + placemark("W1", "<Point><coordinates>75.8,26.9,0</coordinates></Point>") + "</Folder>"
    kml = kml_document(folder_a, folder_b)
    response = upload(client, "two_layers.kml", kml)
    assert response.status_code == 201
    body = client.get(f"/api/files/{response.json()['id']}/measurements/").json()
    assert {f["layer"] for f in body["features"]} == {"Plots", "Wells"}
    assert [f["feature_id"] for f in body["features"]] == [0, 1]


def test_mixed_geometry_collection_is_reported_not_crashed(client):
    multi = (
        "<MultiGeometry><Point><coordinates>75.8,26.9,0</coordinates></Point>"
        "<LineString><coordinates>75.80,26.90,0 75.81,26.90,0</coordinates></LineString></MultiGeometry>"
    )
    kml = kml_document(
        placemark("Mixed", multi),
        placemark("Parcel", polygon_xml(list(SQUARE.exterior.coords)[:-1])),
    )
    response = upload(client, "mixed.kml", kml)
    assert response.status_code == 201
    features = client.get(f"/api/files/{response.json()['id']}/measurements/").json()["features"]
    statuses = {f["properties"]["Name"]: f["measurement_status"] for f in features}
    assert statuses == {"Mixed": "unsupported", "Parcel": "ok"}


def test_invalid_polygon_is_repaired_with_message(client, tmp_path):
    from shapely.geometry import Polygon

    bowtie = Polygon([(75.80, 26.90), (75.81, 26.91), (75.81, 26.90), (75.80, 26.91)])
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[bowtie], crs=4326)
    response = upload(client, "bow.zip", zip_shapefile(gdf, tmp_path))
    feature = client.get(f"/api/files/{response.json()['id']}/measurements/").json()["features"][0]
    assert feature["measurement_status"] == "ok"
    assert "repaired" in feature["message"]


# ---------- missing CRS ----------
def test_shapefile_without_prj_is_rejected_and_recorded(client, tmp_path, square_gdf):
    response = upload(client, "noprj.zip", zip_shapefile(square_gdf, tmp_path, keep_prj=False))
    assert response.status_code == 422
    body = response.json()
    assert "no CRS" in body["detail"]
    assert body["status"] == "FAILED"
    # the failure is stored and can be looked up
    info = client.get(f"/api/files/{body['id']}/").json()
    assert info["status"] == "FAILED"
    assert "assume_crs" in info["error_message"]
    # measurements are not available for a failed file
    assert client.get(f"/api/files/{body['id']}/measurements/").status_code == 409


def test_shapefile_without_prj_accepted_with_assume_crs(client, tmp_path, square_gdf):
    response = upload(client, "noprj.zip", zip_shapefile(square_gdf, tmp_path, keep_prj=False), assume_crs="EPSG:4326")
    assert response.status_code == 201
    assert response.json()["crs"] == "EPSG:4326"


def test_invalid_assume_crs_is_rejected(client, tmp_path, square_gdf):
    response = upload(client, "x.zip", zip_shapefile(square_gdf, tmp_path), assume_crs="not-a-crs")
    assert response.status_code == 400


# ---------- upload validation ----------
def test_unsupported_extension(client):
    response = upload(client, "notes.txt", b"hello")
    assert response.status_code == 415


def test_empty_file(client):
    assert upload(client, "empty.kml", b"").status_code == 400


def test_corrupt_zip(client):
    assert upload(client, "bad.zip", b"this is not a zip").status_code == 400


def test_zip_without_shp(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("readme.txt", "no shapefile here")
    assert upload(client, "empty.zip", buffer.getvalue()).status_code == 400


def test_zip_slip_is_blocked(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("../../evil.shp", "x")
    response = upload(client, "evil.zip", buffer.getvalue())
    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"]


def test_zip_with_too_many_entries(client, monkeypatch):
    monkeypatch.setenv("MAX_ZIP_ENTRIES", "2")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for i in range(5):
            zf.writestr(f"f{i}.txt", "x")
    assert upload(client, "many.zip", buffer.getvalue()).status_code == 413


def test_oversized_upload(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    assert upload(client, "big.kml", b"x" * (1024 * 1024 + 10)).status_code == 413


def test_malformed_kml_is_recorded_as_failed(client):
    response = upload(client, "broken.kml", b"<kml><Document><Placemark></kml>")
    assert response.status_code == 422
    assert response.json()["status"] == "FAILED"


def test_kml_with_no_features(client):
    response = upload(client, "empty_doc.kml", kml_document())
    assert response.status_code == 422


def test_path_in_filename_is_stripped(client):
    kml = kml_document(placemark("P", polygon_xml(list(SQUARE.exterior.coords)[:-1])))
    response = upload(client, "../../etc/passwd.kml", kml)
    assert response.status_code == 201
    assert response.json()["filename"] == "passwd.kml"


# ---------- reading results ----------
def test_unknown_file_id_returns_404(client):
    assert client.get("/api/files/does-not-exist/").status_code == 404
    assert client.get("/api/files/does-not-exist/measurements/").status_code == 404


def test_pagination_and_geometry_toggle(client, tmp_path):
    points = [LineString([(75.80 + i * 0.01, 26.90), (75.81 + i * 0.01, 26.90)]) for i in range(5)]
    gdf = gpd.GeoDataFrame({"n": list(range(5))}, geometry=points, crs=4326)
    file_id = upload(client, "lines.zip", zip_shapefile(gdf, tmp_path)).json()["id"]

    page = client.get(f"/api/files/{file_id}/measurements/", params={"limit": 2, "offset": 1, "include_geometry": "false"}).json()
    assert page["returned"] == 2
    assert [f["feature_id"] for f in page["features"]] == [1, 2]
    assert all(f["geometry"] is None for f in page["features"])
    assert page["feature_count"] == 5
    # the summary covers the whole file, not just the page
    assert page["summary"]["geometry_type_counts"] == {"LineString": 5}
    assert page["summary"]["total_length_m"] > 4900

    assert client.get(f"/api/files/{file_id}/measurements/", params={"limit": 0}).status_code == 422


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
