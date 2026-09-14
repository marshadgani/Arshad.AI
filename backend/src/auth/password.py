"""bcrypt password hashing, off the event loop.

All bcrypt contact with the system funnels through the single private
``_checkpw`` primitive so ``verify_password`` and ``dummy_verify`` are
timing-equivalent (identical pre-hash, identical threadpool dispatch,
identical cost factor) and so tests can assert "exactly one bcrypt op per
request" by spying on ONE symbol instead of two. Two independent spy
targets would make that invariant unfalsifiable — a handler that called
both a decoy AND a real check on one branch would still satisfy "each
symbol called at most once" while violating "exactly one bcrypt op".

bcrypt cost 12 costs roughly 250-400ms of blocking CPU per call, which
would stall every concurrent request if run on the event loop — every
call here is dispatched through starlette's threadpool.
"""

from __future__ import annotations

import base64
import hashlib

import bcrypt
from starlette.concurrency import run_in_threadpool

_BCRYPT_COST = 12

# Computed once at import time. A per-request decoy hash would itself cost
# a second bcrypt operation and defeat the invariant it exists to protect.
_DUMMY_HASH = bcrypt.hashpw(
    b"dummy-password-never-matches-anything", bcrypt.gensalt(_BCRYPT_COST)
)


def _prehash(plain: str) -> bytes:
    # bcrypt silently truncates input at 72 bytes. Pre-hashing with SHA-256
    # (then base64-encoding to stay within bcrypt's ASCII input contract)
    # removes that truncation cliff for long passwords, on both the
    # hash and the verify side.
    return base64.b64encode(hashlib.sha256(plain.encode("utf-8")).digest())


def _checkpw_sync(plain: str, hashed: bytes) -> bool:
    """The ONLY bcrypt comparison call site in the codebase. Tests spy on this."""
    return bcrypt.checkpw(_prehash(plain), hashed)


async def _checkpw(plain: str, hashed: bytes) -> bool:
    return await run_in_threadpool(_checkpw_sync, plain, hashed)


async def hash_password(plain: str) -> str:
    def _hash() -> bytes:
        return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt(_BCRYPT_COST))

    hashed = await run_in_threadpool(_hash)
    return hashed.decode("ascii")


async def verify_password(plain: str, hashed: str) -> bool:
    return await _checkpw(plain, hashed.encode("ascii"))


async def dummy_verify(plain: str) -> None:
    """Constant-time decoy: runs the identical bcrypt path against a fixed
    hash so a request on the user-not-found / OAuth-only-account branch
    costs the same bcrypt CPU as a real verification, closing the timing
    oracle.

    Call ONLY on branches where no real bcrypt has executed (user not
    found, or ``password_hash IS NULL``). The invariant every caller must
    preserve is: exactly one bcrypt operation per request, on every
    branch — never zero, never two.
    """
    await _checkpw(plain, _DUMMY_HASH)


__all__ = ["hash_password", "verify_password", "dummy_verify"]
