"""Whoop domain services.

`api/v1/whoop.py` was a single 538-line module holding six unrelated
concerns: upstream HTTP transport, a 50-entry sport reference table, wire
parsing, integration-state lifecycle, rate limiting, and HTTP routing.
They are separated here so each can be read, tested, and changed alone:

    client.py   upstream transport      (no DB, no FastAPI)
    sports.py   sport-id reference data (pure data)
    parsers.py  wire dict -> schema     (pure functions)
    state.py    integration lifecycle   (DB, no HTTP transport)
    tokens.py   OAuth-provider seam     (the one import of the provider layer)

The router keeps only routing and wire-shape concerns.

Nothing in this package persists biometric values. Recovery, sleep, strain,
HRV and workout data are fetched live per request and handed straight to
the response — see the standing decision in
integrations/personal/oauth_providers.py.
"""
