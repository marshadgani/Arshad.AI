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
    url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys?limit=1"
    r = httpx.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    deploys = r.json()
    if not deploys:
        raise RuntimeError("No deploys found for this service.")
    return deploys[0]["deploy"]


def main() -> None:
    print(f"Polling Render deploy status for service {SERVICE_ID}...")
    elapsed = 0

    while elapsed < MAX_WAIT:
        deploy = get_latest_deploy()
        status = deploy.get("status", "unknown")
        deploy_id = deploy.get("id", "?")
        print(f"  [{elapsed}s] Deploy {deploy_id}: {status}")

        if status in ("live", "deactivated"):
            print(f"✅ Deploy finished with status: {status}")
            sys.exit(0)

        if status in ("build_failed", "update_failed", "canceled"):
            print(f"❌ Deploy failed with status: {status}")
            # Don't exit 1 — let the heal loop handle it
            sys.exit(0)

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    print(f"⚠️ Timed out waiting for deploy after {MAX_WAIT}s")
    sys.exit(0)  # Continue to health check even on timeout


if __name__ == "__main__":
    main()
