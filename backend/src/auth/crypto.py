"""AES-GCM symmetric encryption for OAuth tokens at rest.

Layout of stored ciphertext (bytea column):
    [12-byte nonce][ciphertext + 16-byte GCM tag]

Key comes from OAUTH_ENCRYPTION_KEY (URL-safe base64, 32 bytes raw).
Rotating the key without re-encrypting all rows locks every user out.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


def _load_key() -> bytes:
    raw = os.getenv("OAUTH_ENCRYPTION_KEY")
    if not raw:
        raise RuntimeError(
            "OAUTH_ENCRYPTION_KEY is not set. "
            'Generate with: python3 -c "import secrets, base64; '
            'print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"'
        )
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise RuntimeError("OAUTH_ENCRYPTION_KEY is not valid URL-safe base64") from exc
    if len(key) != 32:
        raise RuntimeError(
            f"OAUTH_ENCRYPTION_KEY must decode to 32 bytes (got {len(key)})"
        )
    return key


def encrypt(plaintext: str) -> bytes:
    aesgcm = AESGCM(_load_key())
    nonce = os.urandom(_NONCE_LEN)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ct


def decrypt(blob: bytes) -> str:
    if len(blob) <= _NONCE_LEN:
        raise ValueError("ciphertext shorter than nonce length")
    aesgcm = AESGCM(_load_key())
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    pt = aesgcm.decrypt(nonce, ct, associated_data=None)
    return pt.decode("utf-8")
