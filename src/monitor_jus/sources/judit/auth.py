"""Autenticação pluggable de webhooks Judit."""

from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from typing import Mapping

from monitor_jus.config import Settings
from monitor_jus.exceptions import ConfigurationError, WebhookAuthError


class WebhookAuthenticator(ABC):
    @abstractmethod
    def validate(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        raise NotImplementedError


class NoneAuthenticator(WebhookAuthenticator):
    def validate(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        return True


class StaticTokenAuthenticator(WebhookAuthenticator):
    def __init__(self, token: str, header_name: str = "x-webhook-token") -> None:
        self.token = token
        self.header_name = header_name.lower()

    def validate(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        normalized = {k.lower(): v for k, v in headers.items()}
        # também aceita Authorization: Bearer
        candidate = normalized.get(self.header_name) or normalized.get("x-api-key")
        auth = normalized.get("authorization", "")
        if auth.lower().startswith("bearer "):
            candidate = candidate or auth.split(" ", 1)[1].strip()
        if not self.token:
            raise WebhookAuthError("JUDIT_WEBHOOK_TOKEN não configurado")
        return hmac.compare_digest(candidate or "", self.token)


class HmacAuthenticator(WebhookAuthenticator):
    def __init__(self, secret: str, header_name: str, algorithm: str = "sha256") -> None:
        self.secret = secret.encode("utf-8")
        self.header_name = header_name.lower()
        self.algorithm = algorithm

    def validate(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        normalized = {k.lower(): v for k, v in headers.items()}
        signature = normalized.get(self.header_name, "")
        if not signature or not self.secret:
            return False
        digest = hmac.new(self.secret, raw_body, getattr(hashlib, self.algorithm)).hexdigest()
        # aceita prefixos tipo sha256=
        provided = signature.split("=")[-1].strip()
        return hmac.compare_digest(provided, digest)


class IpAllowlistAuthenticator(WebhookAuthenticator):
    def __init__(self, allowed_ips: list[str]) -> None:
        self.allowed = set(allowed_ips)

    def validate(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        normalized = {k.lower(): v for k, v in headers.items()}
        # X-Forwarded-For first hop
        xff = normalized.get("x-forwarded-for", "")
        ip = (xff.split(",")[0].strip() if xff else "") or normalized.get("x-real-ip", "")
        return bool(ip) and ip in self.allowed


def build_webhook_authenticator(settings: Settings) -> WebhookAuthenticator:
    mode = settings.judit_webhook_auth_mode
    if settings.is_production and mode == "none":
        raise ConfigurationError(
            "JUDIT_WEBHOOK_AUTH_MODE=none é proibido em produção"
        )
    if mode == "none":
        return NoneAuthenticator()
    if mode == "static_token":
        header = settings.judit_webhook_signature_header or "x-webhook-token"
        return StaticTokenAuthenticator(settings.judit_webhook_token, header)
    if mode == "hmac":
        if not settings.judit_webhook_signature_header:
            raise ConfigurationError("JUDIT_WEBHOOK_SIGNATURE_HEADER obrigatório para hmac")
        return HmacAuthenticator(
            settings.judit_webhook_token,
            settings.judit_webhook_signature_header,
            settings.judit_webhook_signature_algorithm or "sha256",
        )
    if mode == "ip_allowlist":
        return IpAllowlistAuthenticator(settings.webhook_allowed_ip_list)
    raise ConfigurationError(f"Modo de auth webhook desconhecido: {mode}")
