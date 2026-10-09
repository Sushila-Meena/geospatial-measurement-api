"""Domain errors. The HTTP layer maps these to status codes (see app/main.py)."""
from __future__ import annotations

from typing import Optional


class InvalidUploadError(Exception):
    """The upload is rejected before any processing (bad type, too big, unsafe ZIP).

    No database record is created for these.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GeoProcessingError(Exception):
    """The file was accepted but its geospatial content could not be processed.

    A FAILED file record is stored so the client can look the error up later.
    """

    def __init__(self, message: str, file_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.file_id = file_id
