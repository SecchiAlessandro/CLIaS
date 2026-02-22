"""Unit tests for clias.specgen.api_parser — pure logic, no mocks needed."""

from __future__ import annotations

import json

from clias.specgen.api_parser import (
    is_api_command,
    parse_curl,
    parse_httpie,
    extract_response_schema,
    sanitize_body,
)


class TestIsApiCommand:
    def test_curl(self):
        assert is_api_command("curl https://api.github.com/repos") is True

    def test_httpie_http(self):
        assert is_api_command("http GET https://example.com/api") is True

    def test_httpie_https(self):
        assert is_api_command("https example.com/api") is True

    def test_non_api(self):
        assert is_api_command("git status") is False
        assert is_api_command("docker ps") is False
        assert is_api_command("") is False


class TestParseCurl:
    def test_simple_get(self):
        result = parse_curl("curl https://api.github.com/repos/octocat/Hello-World")
        assert result is not None
        assert result["http_method"] == "GET"
        assert result["base_url"] == "https://api.github.com"
        assert result["path"] == "/repos/octocat/Hello-World"
        assert result["path_template"] == "/repos/{owner}/{repo}"

    def test_explicit_method(self):
        result = parse_curl("curl -X POST https://api.example.com/items")
        assert result is not None
        assert result["http_method"] == "POST"

    def test_headers_and_auth(self):
        cmd = "curl -H 'Authorization: Bearer $GITHUB_TOKEN' https://api.github.com/user"
        result = parse_curl(cmd)
        assert result is not None
        assert result["headers"]["Authorization"] == "Bearer $GITHUB_TOKEN"
        assert result["auth_env_var"] == "GITHUB_TOKEN"
        assert result["auth_type"] == "token"

    def test_json_body(self):
        cmd = '''curl -X POST -d '{"title":"bug","body":"details"}' https://api.github.com/repos/o/r/issues'''
        result = parse_curl(cmd)
        assert result is not None
        assert result["http_method"] == "POST"
        assert result["request_body"] == {"title": "bug", "body": "details"}

    def test_implicit_post_with_data(self):
        cmd = "curl -d '{\"key\": \"val\"}' https://api.example.com/items"
        result = parse_curl(cmd)
        assert result is not None
        assert result["http_method"] == "POST"

    def test_query_params(self):
        cmd = "curl 'https://api.example.com/search?q=test&page=1'"
        result = parse_curl(cmd)
        assert result is not None
        assert "q" in result["query_params"]
        assert "page" in result["query_params"]

    def test_basic_auth(self):
        cmd = "curl -u $MY_USER:$MY_PASS https://api.example.com/data"
        result = parse_curl(cmd)
        assert result is not None
        assert result["auth_type"] == "basic"
        assert result["auth_env_var"] == "MY_USER"

    def test_response_parsing(self):
        stdout = json.dumps({"id": 123, "name": "test", "active": True})
        result = parse_curl("curl https://api.example.com/items/123", stdout)
        assert result is not None
        assert result["response_schema"] is not None
        assert result["response_schema"]["id"] == 0
        assert result["response_schema"]["name"] == ""
        assert result["response_schema"]["active"] is False

    def test_returns_none_for_non_curl(self):
        assert parse_curl("git status") is None

    def test_returns_none_for_no_url(self):
        assert parse_curl("curl -v") is None


class TestParseHttpie:
    def test_simple_get(self):
        result = parse_httpie("http GET https://api.github.com/repos/octocat/Hello-World")
        assert result is not None
        assert result["http_method"] == "GET"
        assert result["base_url"] == "https://api.github.com"

    def test_post_with_body(self):
        result = parse_httpie("http POST https://api.example.com/items name=test value=42")
        assert result is not None
        assert result["http_method"] == "POST"
        assert result["request_body"] == {"name": "test", "value": "42"}

    def test_headers(self):
        result = parse_httpie("http GET https://api.example.com/data Authorization:'Bearer $TOKEN'")
        assert result is not None
        assert "Authorization" in result["headers"]

    def test_implicit_post(self):
        result = parse_httpie("http https://api.example.com/items name=foo")
        assert result is not None
        assert result["http_method"] == "POST"

    def test_returns_none_for_non_httpie(self):
        assert parse_httpie("curl https://example.com") is None


class TestExtractResponseSchema:
    def test_simple_object(self):
        stdout = json.dumps({"id": 42, "name": "Alice", "active": True, "score": 3.14})
        schema = extract_response_schema(stdout)
        assert schema == {"id": 0, "name": "", "active": False, "score": 0.0}

    def test_nested_object(self):
        stdout = json.dumps({"user": {"id": 1, "name": "Bob"}, "count": 5})
        schema = extract_response_schema(stdout)
        assert schema["user"] == {"id": 0, "name": ""}
        assert schema["count"] == 0

    def test_array_response(self):
        stdout = json.dumps([{"id": 1}, {"id": 2}])
        schema = extract_response_schema(stdout)
        assert isinstance(schema, list)
        assert len(schema) == 1
        assert schema[0] == {"id": 0}

    def test_depth_cap(self):
        deep = {"a": {"b": {"c": {"d": "too deep"}}}}
        schema = extract_response_schema(json.dumps(deep))
        assert schema["a"]["b"]["c"] == "..."

    def test_null_values(self):
        stdout = json.dumps({"field": None})
        schema = extract_response_schema(stdout)
        assert schema["field"] is None

    def test_empty_string(self):
        assert extract_response_schema("") is None

    def test_invalid_json(self):
        assert extract_response_schema("not json at all") is None


class TestSanitizeBody:
    def test_replaces_long_strings(self):
        body = {"key": "a" * 100}
        result = sanitize_body(body)
        assert result["key"] == "<value>"

    def test_replaces_sensitive_keys(self):
        body = {"api_key": "sk-123", "password": "hunter2", "name": "safe"}
        result = sanitize_body(body)
        assert result["api_key"] == "<value>"
        assert result["password"] == "<value>"
        assert result["name"] == "safe"

    def test_preserves_short_safe_values(self):
        body = {"title": "hello", "count": 5}
        result = sanitize_body(body)
        assert result["title"] == "hello"
        assert result["count"] == 5

    def test_nested_dicts(self):
        body = {"outer": {"secret_key": "value"}}
        result = sanitize_body(body)
        assert result["outer"]["secret_key"] == "<value>"

    def test_none_input(self):
        assert sanitize_body(None) is None


class TestPathTemplating:
    def test_github_repos(self):
        result = parse_curl("curl https://api.github.com/repos/octocat/Hello-World/issues")
        assert result["path_template"] == "/repos/{owner}/{repo}/issues"

    def test_github_users(self):
        result = parse_curl("curl https://api.github.com/users/octocat/repos")
        assert result["path_template"] == "/users/{user}/repos"

    def test_numeric_ids(self):
        result = parse_curl("curl https://api.example.com/items/12345")
        assert result["path_template"] == "/items/{id}"

    def test_hex_ids(self):
        result = parse_curl("curl https://api.example.com/objects/abcdef1234567890")
        assert result["path_template"] == "/objects/{id}"

    def test_prefixed_ids(self):
        result = parse_curl("curl https://api.stripe.com/v1/charges/ch_1234abc")
        assert result["path_template"] == "/v1/charges/{id}"
