"""Upload handling: type detection, size limits and safe ZIP extraction."""
from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from app.config import Settings
from app.services.errors import InvalidUploadError

KML = "kml"
SHAPEFILE = "shapefile"
CHUNK = 1024 * 1024


def detect_file_type(filename: str) -> str:
    """Map a filename to 'kml' or 'shapefile' (a .zip), else reject with 415."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".kml":
        return KML
    if suffix == ".zip":
        return SHAPEFILE
    raise InvalidUploadError("Unsupported file type. Upload a .kml file or a .zip containing a Shapefile.", 415)


def safe_filename(filename: str) -> str:
    """Strip any directory part so a client-supplied name can never be a path."""
    name = PurePosixPath(filename.replace("\\", "/")).name
    return name[:255] or "upload"


def save_upload(stream: BinaryIO, destination: Path, settings: Settings) -> int:
    """Copy the upload to disk in chunks, enforcing the size limit. Returns bytes written."""
    size = 0
    with open(destination, "wb") as out:
        while chunk := stream.read(CHUNK):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise InvalidUploadError(f"File is larger than the {settings.max_upload_mb} MB limit.", 413)
            out.write(chunk)
    if size == 0:
        raise InvalidUploadError("The uploaded file is empty.", 400)
    return size


def extract_zip_safely(zip_path: Path, target_dir: Path, settings: Settings) -> list[Path]:
    """Extract a ZIP after checking it for zip-slip, symlinks and zip bombs.

    Protections:
      * entries with absolute paths or '..' parts are rejected (zip-slip)
      * symbolic links are rejected
      * the number of entries and the total uncompressed size are limited, and the
        size is enforced on the bytes actually written (declared sizes can lie)
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise InvalidUploadError("The file is not a valid ZIP archive.") from exc

    target_root = target_dir.resolve()
    extracted: list[Path] = []
    written_total = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > settings.max_zip_entries:
            raise InvalidUploadError(f"ZIP contains more than {settings.max_zip_entries} files.", 413)
        if sum(i.file_size for i in infos) > settings.max_uncompressed_bytes:
            raise InvalidUploadError(f"ZIP expands to more than {settings.max_uncompressed_mb} MB.", 413)

        for info in infos:
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise InvalidUploadError("ZIP contains an unsafe file path.")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise InvalidUploadError("ZIP contains a symbolic link, which is not allowed.")
            if any(p.startswith(".") or p == "__MACOSX" for p in parts):
                continue  # hidden files and macOS metadata

            target = (target_root / Path(*parts)).resolve()
            if not target.is_relative_to(target_root):
                raise InvalidUploadError("ZIP contains an unsafe file path.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(CHUNK):
                    written_total += len(chunk)
                    if written_total > settings.max_uncompressed_bytes:
                        raise InvalidUploadError(f"ZIP expands to more than {settings.max_uncompressed_mb} MB.", 413)
                    dst.write(chunk)
            extracted.append(target)
    return extracted


def find_shapefiles(files: list[Path]) -> list[Path]:
    """Return the .shp files among extracted files, or reject the ZIP."""
    shps = sorted(p for p in files if p.suffix.lower() == ".shp")
    if not shps:
        raise InvalidUploadError("The ZIP does not contain a .shp file.")
    return shps
