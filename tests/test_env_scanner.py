"""Unit tests for clias.specgen.env_scanner — patched env, values never exposed."""

from __future__ import annotations

import os
from unittest.mock import patch

from clias.specgen.env_scanner import scan_env


class TestScanEnv:
    def test_detects_known_var(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_secret123"}, clear=True):
            results = scan_env()
        assert len(results) == 1
        assert results[0]["env_var"] == "GITHUB_TOKEN"
        assert results[0]["service"] == "github"
        assert results[0]["base_url"] == "https://api.github.com"
        assert results[0]["auth_type"] == "token"

    def test_detects_multiple_known_vars(self):
        env = {
            "GITHUB_TOKEN": "secret1",
            "STRIPE_SECRET_KEY": "secret2",
            "SLACK_TOKEN": "secret3",
        }
        with patch.dict(os.environ, env, clear=True):
            results = scan_env()
        services = {r["service"] for r in results}
        assert "github" in services
        assert "stripe" in services
        assert "slack" in services

    def test_pattern_match_unknown_var(self):
        with patch.dict(os.environ, {"ACME_API_KEY": "secret"}, clear=True):
            results = scan_env()
        assert len(results) == 1
        assert results[0]["env_var"] == "ACME_API_KEY"
        assert results[0]["service"] == "acme"
        assert results[0]["auth_type"] == "api_key"

    def test_pattern_match_token_suffix(self):
        with patch.dict(os.environ, {"CUSTOM_SERVICE_TOKEN": "tok"}, clear=True):
            results = scan_env()
        assert len(results) == 1
        assert results[0]["env_var"] == "CUSTOM_SERVICE_TOKEN"
        assert results[0]["service"] == "custom_service"

    def test_no_match(self):
        with patch.dict(os.environ, {"HOME": "/home/user", "PATH": "/usr/bin"}, clear=True):
            results = scan_env()
        assert results == []

    def test_values_never_exposed(self):
        env = {
            "GITHUB_TOKEN": "ghp_super_secret_do_not_leak",
            "MY_SECRET_KEY": "very-secret",
        }
        with patch.dict(os.environ, env, clear=True):
            results = scan_env()
        for r in results:
            # The result dict should never contain actual secret values
            for v in r.values():
                assert "ghp_super_secret" not in str(v)
                assert "very-secret" not in str(v)

    def test_known_var_takes_priority_over_pattern(self):
        """GITHUB_TOKEN should be matched as known, not as a pattern fallback."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "secret"}, clear=True):
            results = scan_env()
        assert len(results) == 1
        assert results[0]["base_url"] == "https://api.github.com"

    def test_gh_token_alias(self):
        with patch.dict(os.environ, {"GH_TOKEN": "secret"}, clear=True):
            results = scan_env()
        assert len(results) == 1
        assert results[0]["service"] == "github"

    def test_empty_env(self):
        with patch.dict(os.environ, {}, clear=True):
            results = scan_env()
        assert results == []
