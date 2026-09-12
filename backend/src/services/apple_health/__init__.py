"""Apple Health domain services.

Apple Health arrives by push (an iOS Shortcut POSTing to /api/v1/apple-health/
ingest), because HealthKit is an on-device framework with no cloud API for a
server to pull from. Three separable concerns follow from that, and each gets
its own module here — mirroring the layout of services/whoop/:

    envelope.py        seal/unseal a snapshot   (crypto only, no storage)
    snapshot_store.py  where a snapshot lives   (Redis key, TTL, read policy)
    ingest_auth.py     who is allowed to push   (token digest, DB lookup)

They were previously one flat module holding only the primitives, with the
policy that used them spread across the router and the provider: the router
did token lookup, Redis I/O, and HTTP mapping in one file, while the provider
re-derived the cache key twice. Each concern now has exactly one home, and
the router is left with routing and wire shape.

Nothing in this package writes a biometric value in cleartext to any store.
`envelope.encode_snapshot` AES-GCM seals before anything reaches Redis, and
nothing here touches Postgres with a biometric field at all — see the
standing decision in integrations/personal/oauth_providers.py.
"""
