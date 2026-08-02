import pytest

from monitor_jus.mail.resend_mailer import parse_recipients
from monitor_jus.web.services.actions import normalize_email_to


def test_parse_recipients():
    assert parse_recipients("a@x.com, b@y.com") == ["a@x.com", "b@y.com"]
    assert parse_recipients("a@x.com; b@y.com") == ["a@x.com", "b@y.com"]


def test_normalize_email_to():
    assert normalize_email_to("Info@Example.com") == "info@example.com"


def test_normalize_email_to_invalid():
    with pytest.raises(ValueError):
        normalize_email_to("nao-e-email")
