"""Pure-Python parser for curl/httpie commands — extracts API structure without LLM calls."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse, parse_qs


def is_api_command(command: str) -> bool:
    """Return True if the command is a curl or httpie invocation."""
    first = command.strip().split()[0] if command.strip() else ""
    return first in ("curl", "http", "https")


def parse_curl(command: str, stdout: str = "") -> dict | None:
    """Extract API structure from a curl command string and its stdout."""
    if not command.strip().startswith("curl"):
        return None

    tokens = _tokenize(command)
    url = ""
    http_method = "GET"
    headers: dict[str, str] = {}
    body_raw: str | None = None
    auth_env_var: str | None = None
    auth_type: str | None = None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-X", "--request") and i + 1 < len(tokens):
            http_method = tokens[i + 1].upper()
            i += 2
        elif tok in ("-H", "--header") and i + 1 < len(tokens):
            hdr = tokens[i + 1]
            if ":" in hdr:
                name, _, value = hdr.partition(":")
                name = name.strip()
                value = value.strip()
                headers[name] = value
                # Detect env var references in header values
                env_match = re.search(r"\$\{?([A-Z][A-Z0-9_]+)\}?", value)
                if env_match:
                    auth_env_var = env_match.group(1)
                    auth_type = _guess_auth_type(name, value)
            i += 2
        elif tok in ("-d", "--data", "--data-raw", "--data-binary", "--json") and i + 1 < len(tokens):
            body_raw = tokens[i + 1]
            if http_method == "GET":
                http_method = "POST"
            i += 2
        elif tok in ("-u", "--user") and i + 1 < len(tokens):
            auth_type = "basic"
            cred = tokens[i + 1]
            env_match = re.search(r"\$\{?([A-Z][A-Z0-9_]+)\}?", cred)
            if env_match:
                auth_env_var = env_match.group(1)
            i += 2
        elif not tok.startswith("-") and not url:
            # First non-flag token that looks like a URL
            if tok.startswith("http://") or tok.startswith("https://") or tok.startswith("$"):
                url = tok
            i += 1
        else:
            i += 1

    if not url:
        return None

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else url
    path = parsed.path or "/"
    query_params = list(parse_qs(parsed.query).keys())

    # Templatize path segments that look like IDs/names
    path_template = _templatize_path(path)

    # Parse request body
    request_body = None
    if body_raw:
        try:
            request_body = json.loads(body_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse response
    response_schema = extract_response_schema(stdout)

    return {
        "http_method": http_method,
        "url": url,
        "base_url": base_url,
        "path": path,
        "path_template": path_template,
        "headers": headers,
        "query_params": query_params,
        "request_body": sanitize_body(request_body) if request_body else None,
        "response_schema": response_schema,
        "auth_env_var": auth_env_var,
        "auth_type": auth_type,
        "source_command": command,
    }


def parse_httpie(command: str, stdout: str = "") -> dict | None:
    """Extract API structure from an httpie command string and its stdout."""
    tokens = _tokenize(command)
    if not tokens or tokens[0] not in ("http", "https"):
        return None

    # httpie: http [METHOD] URL [items...]
    idx = 1
    http_method = "GET"
    url = ""
    headers: dict[str, str] = {}
    body_fields: dict[str, str] = {}
    auth_env_var: str | None = None
    auth_type: str | None = None

    # Check if second token is an HTTP method
    if idx < len(tokens) and tokens[idx].upper() in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
        http_method = tokens[idx].upper()
        idx += 1

    # Next token should be the URL
    if idx < len(tokens):
        url = tokens[idx]
        # httpie allows shorthand URLs without scheme
        if not url.startswith("http://") and not url.startswith("https://"):
            if tokens[0] == "https":
                url = "https://" + url
            else:
                url = "http://" + url
        idx += 1

    # Remaining tokens: Header:Value, field=value, field:=json_value
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in ("-a", "--auth") and idx + 1 < len(tokens):
            auth_type = "basic"
            cred = tokens[idx + 1]
            env_match = re.search(r"\$\{?([A-Z][A-Z0-9_]+)\}?", cred)
            if env_match:
                auth_env_var = env_match.group(1)
            idx += 2
        elif ":" in tok and not tok.startswith("-") and "=" not in tok.split(":")[0]:
            # Header:Value (no = before the :)
            name, _, value = tok.partition(":")
            headers[name.strip()] = value.strip()
            env_match = re.search(r"\$\{?([A-Z][A-Z0-9_]+)\}?", value)
            if env_match:
                auth_env_var = env_match.group(1)
                auth_type = _guess_auth_type(name, value)
            idx += 1
        elif "==" in tok:
            # Query param: key==value (httpie syntax)
            idx += 1
        elif "=" in tok:
            # Body field
            key, _, val = tok.partition("=")
            body_fields[key] = val
            if http_method == "GET":
                http_method = "POST"
            idx += 1
        else:
            idx += 1

    if not url:
        return None

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else url
    path = parsed.path or "/"
    query_params = list(parse_qs(parsed.query).keys())
    path_template = _templatize_path(path)

    request_body = body_fields if body_fields else None
    response_schema = extract_response_schema(stdout)

    return {
        "http_method": http_method,
        "url": url,
        "base_url": base_url,
        "path": path,
        "path_template": path_template,
        "headers": headers,
        "query_params": query_params,
        "request_body": sanitize_body(request_body) if request_body else None,
        "response_schema": response_schema,
        "auth_env_var": auth_env_var,
        "auth_type": auth_type,
        "source_command": command,
    }


def extract_response_schema(stdout: str) -> dict | None:
    """Parse stdout as JSON and replace scalar values with type sentinels.

    Caps nesting depth at 3 to keep schemas concise.
    """
    if not stdout or not stdout.strip():
        return None
    try:
        data = json.loads(stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    return _schema_from_value(data, depth=0, max_depth=3)


def sanitize_body(body: dict | None) -> dict | None:
    """Replace long strings and sensitive-looking values with '<value>'."""
    if body is None:
        return None
    if not isinstance(body, dict):
        return body

    sensitive_patterns = re.compile(
        r"(token|secret|key|password|auth|credential|api_key|apikey)", re.IGNORECASE
    )
    result = {}
    for k, v in body.items():
        if isinstance(v, str):
            if len(v) > 50 or sensitive_patterns.search(k):
                result[k] = "<value>"
            else:
                result[k] = v
        elif isinstance(v, dict):
            result[k] = sanitize_body(v)
        else:
            result[k] = v
    return result


# ── Internal helpers ──────────────────────────────────────────────────


def _tokenize(command: str) -> list[str]:
    """Split a shell command into tokens, respecting single/double quotes."""
    tokens: list[str] = []
    current = ""
    in_quote: str | None = None

    i = 0
    while i < len(command):
        ch = command[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
            elif ch == "\\" and in_quote == '"' and i + 1 < len(command):
                current += command[i + 1]
                i += 2
                continue
            else:
                current += ch
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch in (" ", "\t"):
            if current:
                tokens.append(current)
                current = ""
        else:
            current += ch
        i += 1
    if current:
        tokens.append(current)
    return tokens


def _templatize_path(path: str) -> str:
    """Replace path segments that look like IDs or specific values with templates.

    Examples:
        /repos/octocat/Hello-World/issues -> /repos/{owner}/{repo}/issues
        /v1/charges/ch_123abc -> /v1/charges/{id}
    """
    # Known patterns for popular APIs
    known_templates = [
        (r"/repos/([^/]+)/([^/]+)", "/repos/{owner}/{repo}"),
        (r"/orgs/([^/]+)", "/orgs/{org}"),
        (r"/users/([^/]+)", "/users/{user}"),
        (r"/gists/([^/]+)", "/gists/{gist_id}"),
    ]
    result = path
    for pattern, replacement in known_templates:
        result = re.sub(pattern, replacement, result, count=1)

    # Generic: replace segments that look like IDs (hex, numeric, or with underscores after a prefix)
    segments = result.split("/")
    for i, seg in enumerate(segments):
        if not seg:
            continue
        # Already templated
        if seg.startswith("{"):
            continue
        # Looks like a specific ID: hex strings, numeric, or prefixed IDs like ch_123abc
        if re.match(r"^[0-9a-f]{8,}$", seg, re.IGNORECASE):
            segments[i] = "{id}"
        elif re.match(r"^\d+$", seg) and i > 0:
            segments[i] = "{id}"
        elif re.match(r"^[a-z]{2,}_[a-zA-Z0-9]+$", seg):
            segments[i] = "{id}"
    return "/".join(segments)


def _guess_auth_type(header_name: str, header_value: str) -> str:
    """Guess the auth type from a header name and value."""
    name_lower = header_name.lower()
    value_lower = header_value.lower()
    if name_lower == "authorization":
        if "bearer" in value_lower:
            return "token"
        if "basic" in value_lower:
            return "basic"
        if "token" in value_lower:
            return "token"
        return "api_key"
    return "api_key"


def _schema_from_value(value: object, depth: int, max_depth: int) -> object:
    """Recursively replace scalar values with type sentinels."""
    if depth >= max_depth:
        return "..."
    if isinstance(value, dict):
        return {k: _schema_from_value(v, depth + 1, max_depth) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        # Just schema-ify the first element as representative
        return [_schema_from_value(value[0], depth + 1, max_depth)]
    if isinstance(value, str):
        return ""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0
    if isinstance(value, float):
        return 0.0
    if value is None:
        return None
    return ""
