"""Application settings, read from environment variables with safe defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./geo_api.db"
    max_upload_mb: int = 50  # largest accepted upload
    max_uncompressed_mb: int = 200  # largest total size a ZIP may expand to
    max_zip_entries: int = 200  # largest number of files inside a ZIP
    max_features: int = 50_000  # largest number of features per file

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_uncompressed_bytes(self) -> int:
        return self.max_uncompressed_mb * 1024 * 1024


def get_settings() -> Settings:
    """Build settings from the environment (read on every call, so tests can override)."""
    defaults = Settings()
    return Settings(
        database_url=os.getenv("DATABASE_URL", defaults.database_url),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", defaults.max_upload_mb)),
        max_uncompressed_mb=int(os.getenv("MAX_UNCOMPRESSED_MB", defaults.max_uncompressed_mb)),
        max_zip_entries=int(os.getenv("MAX_ZIP_ENTRIES", defaults.max_zip_entries)),
        max_features=int(os.getenv("MAX_FEATURES", defaults.max_features)),
    )
