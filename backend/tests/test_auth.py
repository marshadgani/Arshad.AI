"""Tests for /api/v1/auth/* routes."""

from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_logout_returns_204():
    """POST /logout is a stateless no-op — server-side JWT revocation is
    not implemented (see routers.py module docstring for rationale).
    The endpoint must return 204 with no response body."""
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert response.content == b""
