"""Set (or rotate) the password for an existing user. The ONLY writer of
users.password_hash in this codebase — there is no HTTP registration
endpoint (single-user app; OAuth remains the sole account-CREATION path,
see ADR-6 in FEAT-143's system design).

Uses DATABASE_URL (the Supabase pooler), NOT DATABASE_URL_DIRECT. Per
CLAUDE.md section 23, DATABASE_URL_DIRECT is an Alembic-specific
requirement (migration revision resolution needs the direct connection);
a single parameterised UPDATE over the pooler is correct here and this
comment exists so nobody "fixes" it back to DATABASE_URL_DIRECT later.

Usage (inside the Render shell or a container with backend/ on PYTHONPATH):

    python -m scripts.set_password --email you@example.com

Password is read via getpass (never a --password flag — that would land
in shell history and the Render shell audit trail). For non-TTY contexts
only, --from-env NAME reads the password from that environment variable
instead.

Refuses to create a new user — exits non-zero with instructions to sign
in via Google or GitHub first. This keeps OAuth the sole account-creation
path and prevents this script from becoming a backdoor registration
endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.auth.password import hash_password, verify_password  # noqa: E402
from src.auth.service import normalize_email  # noqa: E402
from src.models.user import User  # noqa: E402


def _read_password(from_env: str | None) -> str:
    if from_env:
        value = os.getenv(from_env)
        if not value:
            print(
                f"Environment variable {from_env} is unset or empty.", file=sys.stderr
            )
            sys.exit(1)
        return value
    return getpass.getpass("New password: ")


async def _set_password(email: str, password: str) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)

    email_norm = normalize_email(email)
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with factory() as session:
            user = await session.scalar(select(User).where(User.email == email_norm))
            if user is None:
                print(
                    f"No such user: {email_norm!r}. "
                    "Sign in with Google or GitHub once first, then re-run this script.",
                    file=sys.stderr,
                )
                sys.exit(1)

            hashed = await hash_password(password)
            user.password_hash = hashed
            await session.commit()

            # Re-read and verify before reporting success — never print the
            # password or the hash itself.
            await session.refresh(user)
            if not user.password_hash or not await verify_password(
                password, user.password_hash
            ):
                print(
                    "Verification failed after write — password was NOT confirmed set.",
                    file=sys.stderr,
                )
                sys.exit(1)

        print(f"Password set for {email_norm}.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing user's email address")
    parser.add_argument(
        "--from-env",
        default=None,
        metavar="VAR",
        help="Read the password from this env var instead of an interactive prompt "
        "(non-TTY escape hatch only)",
    )
    args = parser.parse_args()

    password = _read_password(args.from_env)
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_set_password(args.email, password))


if __name__ == "__main__":
    main()
