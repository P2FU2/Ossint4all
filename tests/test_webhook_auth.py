import pytest

from monitor_jus.config import Settings
from monitor_jus.exceptions import ConfigurationError
from monitor_jus.sources.judit.auth import (
    StaticTokenAuthenticator,
    build_webhook_authenticator,
)


def test_static_token_ok():
    auth = StaticTokenAuthenticator("secret", "x-webhook-token")
    assert auth.validate({"x-webhook-token": "secret"}, b"{}") is True
    assert auth.validate({"x-webhook-token": "wrong"}, b"{}") is False


def test_production_forbids_none():
    settings = Settings(env="production", judit_webhook_auth_mode="none")
    with pytest.raises(ConfigurationError):
        build_webhook_authenticator(settings)
