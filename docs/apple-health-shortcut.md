# Apple Health — iOS Shortcut Setup

Apple Health (HealthKit) has no cloud API — Apple never lets a server pull
health data directly. Arshad.AI receives Apple Health metrics by having
your **iPhone push a JSON snapshot** to a dedicated endpoint on a schedule
you control, via the Shortcuts app (or the third-party "Health Auto
Export" app, which can also POST JSON on a schedule).

Biometric values (resting heart rate, HRV, sleep, steps, active energy,
VO2 max) are never persisted to Postgres and are AES-GCM encrypted before
they touch Redis. See `backend/src/integrations/personal/apple_health.py`
for the full data-handling rationale.

## 1. Get your ingest token

1. Open Arshad.AI → **Integrations** → **Apple Health** → **Connect**.
2. A one-time modal shows your ingest token. Copy it immediately — the
   server stores only a SHA-256 hash and **cannot show it to you again**.
3. If you lose the token or need to reconfigure the Shortcut, click
   **Reconnect** on the Apple Health card. This mints a new token and
   immediately invalidates the old one (enforced by
   `uq_ingest_token_one_per_integration` in the database) — there is no
   other recovery path.

## 2. Endpoint

| Environment | URL |
|---|---|
| Production | `https://arshad-ai.onrender.com/api/v1/apple-health/ingest` |
| Local development | `http://localhost:8000/api/v1/apple-health/ingest` |

- **Method:** `POST`
- **Header:** `Authorization: Bearer <your ingest token>`
- **Body:** `application/json`

## 3. JSON body

All fields are optional; send whatever your device can supply. Values
outside physiological plausibility ranges are silently coerced to `null`
(not rejected — the rest of the push still lands) and listed back to you
in the response's `dropped_fields` array, so you can tell a sensor glitch
from a real reading without server-log access.

| Field | Type | Plausible range | HealthKit sample type |
|---|---|---|---|
| `resting_heart_rate` | number (bpm) | 20–250 | `HKQuantityTypeIdentifierRestingHeartRate` |
| `heart_rate_variability_ms` | number (ms) | 5–500 | `HKQuantityTypeIdentifierHeartRateVariabilitySDNN` |
| `sleep_hours` | number (hours) | 0–24 | `HKCategoryTypeIdentifierSleepAnalysis` (cumulative hours) |
| `active_energy_kcal` | number (kcal) | 0–10000 | `HKQuantityTypeIdentifierActiveEnergyBurned` |
| `steps` | integer | 0–200000 | `HKQuantityTypeIdentifierStepCount` |
| `vo2_max` | number (mL/kg/min) | 0–100 | `HKQuantityTypeIdentifierVO2Max` |
| `recorded_at` | ISO-8601 datetime | must not be in the future | timestamp of the underlying sample |

Example body:

```json
{
  "resting_heart_rate": 54,
  "heart_rate_variability_ms": 62.3,
  "sleep_hours": 7.4,
  "active_energy_kcal": 480,
  "steps": 8213,
  "vo2_max": 46.1,
  "recorded_at": "2026-09-07T06:15:00Z"
}
```

Example response (200):

```json
{ "data": { "received": true, "dropped_fields": [] } }
```

If a value was out of range:

```json
{ "data": { "received": true, "dropped_fields": ["resting_heart_rate"] } }
```

## 4. "Health Auto Export" app field-name mapping

If you use the [Health Auto Export](https://www.healthexportapp.com/) app
instead of building your own Shortcut, map its export field names to the
body above:

| Health Auto Export field | Maps to |
|---|---|
| `heart_rate_data.resting` | `resting_heart_rate` |
| `heart_rate_variability` | `heart_rate_variability_ms` |
| `sleep_analysis.total_sleep` (hours) | `sleep_hours` |
| `active_energy` | `active_energy_kcal` |
| `step_count` | `steps` |
| `vo2_max` | `vo2_max` |
| `date` | `recorded_at` |

Unrecognized/extra fields are ignored, not rejected — this app's export
schema changes across versions and a strict parser would break silently
on every update.

## 5. Recommended schedule

Either works well:

- **Hourly automation** (Settings → Shortcuts → Automation → Time of Day,
  repeat hourly), or
- **"When I close the Health app"** personal automation, which pushes a
  fresh snapshot right after you check in.

The server caches your last push for 6 hours; if nothing new arrives in
that window, the dashboard card shows `stale: true` rather than guessing.
There's a per-integration rate limit of 20 pushes/hour, well above either
schedule — it exists only to bound damage from a misconfigured automation
looping.

## 6. If metrics disappear from the dashboard

Two situations look the same from the dashboard (both show `stale: true`
with no error) but have different causes:

1. **Your Shortcut stopped running.** Check Shortcuts → Automation is
   still enabled, and that your last push was within 6 hours.
2. **The server's encryption key was rotated.** This is an internal
   operational event (see `OAUTH_ENCRYPTION_KEY` in `CLAUDE.md` §6) — it
   makes previously cached snapshots undecryptable. This is expected and
   self-heals within 6 hours as soon as your Shortcut's next scheduled
   push writes a fresh snapshot under the new key. No action needed on
   your end.
