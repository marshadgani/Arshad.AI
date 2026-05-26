"""
Wait for the latest Render deploy to reach a terminal state (live or failed).
Polls every 15 seconds for up to 20 minutes.
"""

import os
import sys
import time

import httpx

RENDER_API_KEY = os.environ["RENDER_API_KEY"]
SERVICE_ID = os.environ["RENDER_SERVICE_ID"]
HEADERS = {"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"}
POLL_INTERVAL = 15  # seconds
MAX_WAIT = 20 * 60  # 20 minutes


def get_latest_deploy() -> dict:
    """Fetch the most recent deploy for the service. Raises on API error or empty list."""
    url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys?limit=1"
    r = httpx.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    deploys = r.json()
    if not deploys:
        raise RuntimeError("No deploys found for this service.")
    return deploys[0]["deploy"]


def main() -> None:
    """Poll until the latest deploy reaches a terminal state or 20 minutes elapse.

    Exits 0 regardless of deploy outcome — the caller (render_heal.py) reads the
    health endpoint and decides whether to attempt a fix.
    """
    print(f"Polling Render deploy status for service {SERVICE_ID}...")
    elapsed = 0

    while elapsed < MAX_WAIT:
        try:
            deploy = get_latest_deploy()
        except Exception as e:
            print(f"  [{elapsed}s] Could not fetch deploy status: {e}")
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue

        status = deploy.get("status", "unknown")
        deploy_id = deploy.get("id", "?")
        print(f"  [{elapsed}s] Deploy {deploy_id}: {status}")

        if status in ("live", "deactivated"):
            print(f"✅ Deploy finished with status: {status}")
            sys.exit(0)

        if status in ("build_failed", "update_failed", "canceled"):
            print(f"❌ Deploy failed with status: {status}")
            # Exit 0 so the workflow proceeds to the heal step, which will
            # check health, fetch logs, and attempt a code fix.
            sys.exit(0)

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    print(f"⚠️ Timed out waiting for deploy after {MAX_WAIT}s")
    sys.exit(0)  # Continue to health check even on timeout


if __name__ == "__main__":
    main()
