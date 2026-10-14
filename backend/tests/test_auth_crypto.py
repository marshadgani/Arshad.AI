"""AES-GCM token encryption: round trip and failure behaviour.

Guards the cryptography dependency pin, so a major-version bump that changes
the AESGCM API or the tag-failure exception is caught in CI.
"""

from __future__ import annotations

import base64
import os

import pytest
from src.auth import crypto
from src.auth.crypto import TokenDecryptError, decrypt, encrypt


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def _fresh_key(monkeypatch):
    monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", _key())
    monkeypatch.setattr(crypto, "_cached_key", None)
    yield
    monkeypatch.setattr(crypto, "_cached_key", None)


def test_round_trip_preserves_text():
    assert decrypt(encrypt("ya29.token-é-✓")) == "ya29.token-é-✓"


def test_same_plaintext_gives_different_ciphertext():
    assert encrypt("same") != encrypt("same")


def test_wrong_key_raises_token_decrypt_error(monkeypatch):
    blob = encrypt("secret")
    monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", _key())
    monkeypatch.setattr(crypto, "_cached_key", None)

    with pytest.raises(TokenDecryptError):
        decrypt(blob)


def test_tampered_ciphertext_raises_token_decrypt_error():
    blob = bytearray(encrypt("secret"))
    blob[-1] ^= 0x01

    with pytest.raises(TokenDecryptError):
        decrypt(bytes(blob))


def test_truncated_blob_raises_token_decrypt_error():
    with pytest.raises(TokenDecryptError):
        decrypt(b"short")


def test_known_answer_from_the_nist_aes_256_gcm_vector(monkeypatch):
    # NIST GCM test case 13: all-zero 256-bit key, 96-bit IV and 128-bit
    # plaintext. Pins the wire format (nonce, ciphertext, tag) across
    # cryptography releases.
    monkeypatch.setenv(
        "OAUTH_ENCRYPTION_KEY", base64.urlsafe_b64encode(bytes(32)).decode()
    )
    monkeypatch.setattr(crypto, "_cached_key", None)
    blob = (
        bytes(12)
        + bytes.fromhex("cea7403d4d606b6e074ec5d3baf39d18")
        + bytes.fromhex("d0d1c8a799996bf0265b98b5d48ab919")
    )

    assert decrypt(blob) == "\x00" * 16


@pytest.mark.parametrize(
    "raw", ["", "not base64!!", base64.urlsafe_b64encode(b"short").decode()]
)
def test_bad_encryption_key_config_raises_runtime_error(monkeypatch, raw):
    monkeypatch.setenv("OAUTH_ENCRYPTION_KEY", raw)
    monkeypatch.setattr(crypto, "_cached_key", None)

    with pytest.raises(RuntimeError):
        encrypt("x")
