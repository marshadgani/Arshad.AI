"""Gmail integration — fetches the unread inbox count.

Pure I/O adapter. Raises httpx errors on upstream failure; the caller decides
how to degrade. Tolerates a null or absent `messagesUnread` field (returns 0).
"""

from __future__ import annotations

import httpx

GMAIL_INBOX_URL = "https://gmail.googleapis.com/gmail/v1/users/me/labels/INBOX"
_HTTP_TIMEOUT = 10.0


async def fetch_unread_count(access_token: str) -> int:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(GMAIL_INBOX_URL, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    raw_unread = payload.get("messagesUnread")
    if raw_unread is None:
        return 0
    return int(raw_unread)
