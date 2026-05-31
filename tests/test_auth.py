"""Security tests for the Function URL authentication layer."""

import pytest

from bot_common import auth
from bot_common.crypto import issue_token


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)


def test_open_when_no_auth_configured():
    ok, _ = auth.verify_api_key({})
    assert ok is True


def test_api_key_via_x_api_key_header(monkeypatch):
    monkeypatch.setenv("API_KEY", "top-secret")
    ok, _ = auth.verify_api_key({"X-API-Key": "top-secret"})
    assert ok is True


def test_api_key_via_bearer(monkeypatch):
    monkeypatch.setenv("API_KEY", "top-secret")
    ok, _ = auth.verify_api_key({"Authorization": "Bearer top-secret"})
    assert ok is True


def test_api_key_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "top-secret")
    ok, err = auth.verify_api_key({"X-API-Key": "guess"})
    assert ok is False
    assert err


def test_api_key_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("API_KEY", "top-secret")
    ok, _ = auth.verify_api_key({})
    assert ok is False


def test_jwt_bearer_accepted(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    token = issue_token("user-1", "jwt-secret")
    ok, _ = auth.verify_api_key({"Authorization": f"Bearer {token}"})
    assert ok is True


def test_jwt_bearer_rejected_when_forged(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    token = issue_token("user-1", "different-secret")
    ok, _ = auth.verify_api_key({"Authorization": f"Bearer {token}"})
    assert ok is False


def test_expired_jwt_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "jwt-secret")
    token = issue_token("user-1", "jwt-secret", ttl_seconds=-1)
    ok, _ = auth.verify_api_key({"Authorization": f"Bearer {token}"})
    assert ok is False
