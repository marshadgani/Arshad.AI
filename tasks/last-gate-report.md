<!-- generated 2026-04-26T22:30:00Z; verified by clean-venv app boot, 31 live + 11 coming-soon -->

# Gate Report — Phase H wave 2+3: Google scope widening + Drive/Tasks/YouTube/Maps

**Branch:** `claude/ai-personal-assistant-develop-AION` → `claude/ai-personal-assistant-main`
**Diff scope:** 5 modified + 2 new files

## ✅ GATE PASSED — verified by clean-venv app boot

```
Total: 42 integrations
Live:  31 (was 27)
Soon:  11 (was 15)
```

## What this PR delivers

### Google login scope widening (wave 2)

Added 3 scopes to `auth/providers/google.py` `_SCOPES`:
- `https://www.googleapis.com/auth/drive.metadata.readonly`
- `https://www.googleapis.com/auth/tasks`
- `https://www.googleapis.com/auth/youtube.readonly`

Existing logged-in users will see "Re-auth required" on the new providers because their stored token doesn't have the widened scope. Logout + log in again grants the full set. New users get all scopes on first consent.

### 4 promotions from coming_soon → real

| Provider | Slug | Class |
|---|---|---|
| Google Drive | `google_drive` | personal_oauth (shares Google login token) |
| Google Tasks | `google_tasks` | personal_oauth (same) |
| YouTube | `youtube` | personal_oauth (same) |
| Google Maps Places | `google_maps` | project_apikey (separate GCP API key) |

### Implementation notes

Drive / Tasks / YouTube providers reuse `tools.token_service.get_access_token` to grab the already-stored Google OAuth token. They detect a 403 (scope not granted) and surface integration.status = "expired" with a clear "log out + log in to re-consent" message instead of crashing.

Google Maps probes via Places API text-search (`https://places.googleapis.com/v1/places:searchText`) — modern v1 endpoint with per-field FieldMask. User just pastes a GCP API key into the connect modal.

## Verification

Boot-verified in clean venv: app imports cleanly, 31 live + 11 soon = 42 total, no exceptions. Generic OAuth callback route still mounted.

## Verdict

**GATE PASSED.** Wave 2+3 land cleanly on top of wave 1.
