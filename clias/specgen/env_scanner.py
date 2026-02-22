"""Scan environment variables for API key patterns — never exposes actual values."""

from __future__ import annotations

import os
import re

# Known API key env vars with their service metadata.
_KNOWN_VARS: list[dict[str, str]] = [
    {"env_var": "GITHUB_TOKEN", "service": "github", "base_url": "https://api.github.com", "auth_type": "token"},
    {"env_var": "GH_TOKEN", "service": "github", "base_url": "https://api.github.com", "auth_type": "token"},
    {"env_var": "GITLAB_TOKEN", "service": "gitlab", "base_url": "https://gitlab.com/api/v4", "auth_type": "token"},
    {"env_var": "STRIPE_SECRET_KEY", "service": "stripe", "base_url": "https://api.stripe.com", "auth_type": "api_key"},
    {"env_var": "STRIPE_API_KEY", "service": "stripe", "base_url": "https://api.stripe.com", "auth_type": "api_key"},
    {"env_var": "SLACK_TOKEN", "service": "slack", "base_url": "https://slack.com/api", "auth_type": "token"},
    {"env_var": "SLACK_BOT_TOKEN", "service": "slack", "base_url": "https://slack.com/api", "auth_type": "token"},
    {"env_var": "OPENAI_API_KEY", "service": "openai", "base_url": "https://api.openai.com", "auth_type": "api_key"},
    {"env_var": "ANTHROPIC_API_KEY", "service": "anthropic", "base_url": "https://api.anthropic.com", "auth_type": "api_key"},
    {"env_var": "AWS_ACCESS_KEY_ID", "service": "aws", "base_url": "", "auth_type": "api_key"},
    {"env_var": "DOCKER_HOST", "service": "docker", "base_url": "", "auth_type": "none"},
    {"env_var": "HEROKU_API_KEY", "service": "heroku", "base_url": "https://api.heroku.com", "auth_type": "api_key"},
    {"env_var": "TWILIO_AUTH_TOKEN", "service": "twilio", "base_url": "https://api.twilio.com", "auth_type": "token"},
    {"env_var": "SENDGRID_API_KEY", "service": "sendgrid", "base_url": "https://api.sendgrid.com", "auth_type": "api_key"},
    {"env_var": "DATADOG_API_KEY", "service": "datadog", "base_url": "https://api.datadoghq.com", "auth_type": "api_key"},
    {"env_var": "CIRCLECI_TOKEN", "service": "circleci", "base_url": "https://circleci.com/api/v2", "auth_type": "token"},
    {"env_var": "VERCEL_TOKEN", "service": "vercel", "base_url": "https://api.vercel.com", "auth_type": "token"},
    {"env_var": "NETLIFY_AUTH_TOKEN", "service": "netlify", "base_url": "https://api.netlify.com", "auth_type": "token"},
    {"env_var": "DIGITALOCEAN_TOKEN", "service": "digitalocean", "base_url": "https://api.digitalocean.com", "auth_type": "token"},
    {"env_var": "CLOUDFLARE_API_TOKEN", "service": "cloudflare", "base_url": "https://api.cloudflare.com", "auth_type": "token"},
]

# Patterns that suggest an env var holds an API credential.
_CREDENTIAL_PATTERNS = re.compile(
    r"^.+_(TOKEN|API_KEY|APIKEY|SECRET|SECRET_KEY|AUTH_TOKEN|ACCESS_KEY|ACCESS_TOKEN)$"
)


def scan_env() -> list[dict[str, str]]:
    """Scan os.environ for API key patterns.

    Returns a list of dicts with keys: env_var, service, base_url, auth_type.
    Never exposes actual secret values.
    """
    found: list[dict[str, str]] = []
    seen_vars: set[str] = set()

    # Check known vars first
    for entry in _KNOWN_VARS:
        var = entry["env_var"]
        if var in os.environ:
            found.append({
                "env_var": var,
                "service": entry["service"],
                "base_url": entry["base_url"],
                "auth_type": entry["auth_type"],
            })
            seen_vars.add(var)

    # Fallback: pattern-match unknown vars
    for var in sorted(os.environ):
        if var in seen_vars:
            continue
        if _CREDENTIAL_PATTERNS.match(var):
            # Derive a service name from the prefix
            service = _derive_service(var)
            found.append({
                "env_var": var,
                "service": service,
                "base_url": "",
                "auth_type": "api_key",
            })

    return found


def _derive_service(var_name: str) -> str:
    """Derive a service name from an env var name like MY_SERVICE_API_KEY -> my_service."""
    # Strip known suffixes
    for suffix in ("_API_KEY", "_APIKEY", "_SECRET_KEY", "_SECRET", "_AUTH_TOKEN",
                   "_ACCESS_KEY", "_ACCESS_TOKEN", "_TOKEN"):
        if var_name.endswith(suffix):
            return var_name[: -len(suffix)].lower()
    return var_name.lower()
