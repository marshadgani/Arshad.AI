"""Shared Supabase Supavisor pooler guard.

Supavisor runs in two modes:
  - Transaction mode (port 6543): routes each transaction to an arbitrary
    backend, so PREPARE and DEALLOCATE can land on different backends,
    leaving stale named statements (e.g. __asyncpg_stmt_5__) that collide
    with counter-based names from the next asyncpg connection object.
  - Session mode (port 5432): pins one backend connection for the life of
    the client's session, so prepared statements behave like a direct
    connection — safe for asyncpg.

Only Session mode is safe for asyncpg; Transaction mode is rejected
outright. Both backend/src/models/database.py (runtime) and
backend/alembic/env.py (migrations) call this so the two can't drift.
"""

from urllib.parse import urlsplit

TRANSACTION_MODE_PORT = 6543


def is_pooler_url(db_url: str) -> bool:
    """True if db_url's host or username identifies Supabase's Supavisor pooler.

    Hostname is the primary signal; the 'postgres.PROJECT_REF' username
    format is a secondary one, since Supabase could serve the pooler from a
    differently named host (a custom domain, a regional alias, etc.) while
    still requiring the tenant-scoped username.
    """
    parsed = urlsplit(db_url)
    hostname = parsed.hostname or ""
    username = parsed.username or ""
    return "pooler.supabase.com" in hostname or username.startswith("postgres.")


def reject_transaction_mode_pooler(db_url: str) -> None:
    """Raise RuntimeError if db_url points at Supabase's Transaction mode pooler."""
    parsed = urlsplit(db_url)
    try:
        port = parsed.port
    except ValueError as exc:
        # Unparseable port — often an unescaped ':', '@', or '/' in the
        # password. Can't confirm the pooler mode, so fail loudly rather
        # than silently risk running DDL/queries through transaction mode.
        raise RuntimeError(
            f"Could not parse a port from the database URL ({exc}). If the "
            "password contains '@', ':', or '/', percent-encode it."
        ) from exc

    if is_pooler_url(db_url) and port == TRANSACTION_MODE_PORT:
        hostname = parsed.hostname or "<unparsed host>"
        raise RuntimeError(
            "DATABASE_URL points at Supabase's Transaction mode pooler "
            f"({hostname}:{TRANSACTION_MODE_PORT}), which is incompatible "
            "with asyncpg.\n\n"
            "Fix on Render:\n"
            "  1. Go to Supabase dashboard → Project Settings → Database "
            "→ Connection string\n"
            "  2. Select the 'Session mode' pooler connection string "
            "(port 5432)\n"
            "  3. Add +asyncpg after postgresql: → postgresql+asyncpg://...\n"
            "  4. Set DATABASE_URL_DIRECT to that value in Render → Environment\n"
        )
