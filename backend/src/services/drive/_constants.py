"""Module-level constants for the Drive service.

Centralised here so every sub-module imports from one place and
the values are never silently duplicated.
"""

from __future__ import annotations

_SLUG = "google_drive"
_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_FIELDS = (
    "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,"
    "permissions(id,type,role,allowFileDiscovery))"
)
_PAGE_CAP = 3
_REFRESH_REAUTH_STATUSES = range(400, 404)
_API_REAUTH_STATUSES = (401,)
_MAX_NAME_CHARS = 512
_MAX_SUGGESTIONS = 50
