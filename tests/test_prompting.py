"""Tests for clias.prompting — interactive credential prompting."""

from __future__ import annotations

import os

import pytest
from rich.console import Console

from clias.prompting import ask_user_credentials


@pytest.fixture()
def console():
    return Console(quiet=True)


MISSING = [
    {"env_var": "PAYPAL_TOKEN", "service": "paypal", "reason": "referenced in API call"},
    {"env_var": "STRIPE_KEY", "service": "stripe", "reason": "referenced in API call"},
]


class TestAskUserCredentials:
    def test_provides_credentials(self, monkeypatch, console):
        """User provides values for all missing credentials."""
        responses = iter(["my-paypal-token", "my-stripe-key"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: next(responses))

        # Ensure env vars are not set before
        monkeypatch.delenv("PAYPAL_TOKEN", raising=False)
        monkeypatch.delenv("STRIPE_KEY", raising=False)

        result = ask_user_credentials(MISSING, console)

        assert result == {
            "PAYPAL_TOKEN": "my-paypal-token",
            "STRIPE_KEY": "my-stripe-key",
        }
        assert os.environ["PAYPAL_TOKEN"] == "my-paypal-token"
        assert os.environ["STRIPE_KEY"] == "my-stripe-key"

    def test_skip_credentials(self, monkeypatch, console):
        """User skips all credentials by pressing Enter (empty string)."""
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: "")

        monkeypatch.delenv("PAYPAL_TOKEN", raising=False)
        monkeypatch.delenv("STRIPE_KEY", raising=False)

        result = ask_user_credentials(MISSING, console)

        assert result == {}
        assert "PAYPAL_TOKEN" not in os.environ
        assert "STRIPE_KEY" not in os.environ

    def test_partial_skip(self, monkeypatch, console):
        """User provides one credential and skips another."""
        responses = iter(["my-paypal-token", ""])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **kw: next(responses))

        monkeypatch.delenv("PAYPAL_TOKEN", raising=False)
        monkeypatch.delenv("STRIPE_KEY", raising=False)

        result = ask_user_credentials(MISSING, console)

        assert result == {"PAYPAL_TOKEN": "my-paypal-token"}
        assert os.environ["PAYPAL_TOKEN"] == "my-paypal-token"
        assert "STRIPE_KEY" not in os.environ

    def test_empty_missing_list(self, console):
        """No missing credentials returns empty dict without prompting."""
        result = ask_user_credentials([], console)
        assert result == {}
