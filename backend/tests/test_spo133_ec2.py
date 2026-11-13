"""SPO-133: CORS, agent-chat deadline, proxy rate-limit key, SSM env file."""

import asyncio
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import PlainTextResponse

from app.api.agent_deadline import run_agent_chat
from app.main import app
from app.middleware.event_stream import EventStreamCacheControlMiddleware
from app.middleware.rate_limit import (
    PROXY_SECRET_HEADER,
    ProxySecretMiddleware,
    _is_health_path,
    client_address_key,
    limiter,
)
from app.models.agent_chat import AgentChatRequest
from app.settings import Settings, settings

REPO = Path(__file__).resolve().parents[2]
PULL_SCRIPT = REPO / "deploy" / "pull-ssm-env.sh"
SSM_FIXTURES = REPO / "backend" / "tests" / "fixtures" / "ssm"
SSM_PAGE1 = (SSM_FIXTURES / "get-parameters-by-path-page1.json").read_text(encoding="utf-8")
SSM_PAGE2 = (SSM_FIXTURES / "get-parameters-by-path-page2.json").read_text(encoding="utf-8")
PEER = "198.51.100.9"
SECRET = "correct-secret-value"
PREVIEW_REGEX = (
    r"^https://sports-lab(-git-[a-z0-9-]+-team|-[a-z0-9]+-team)\.vercel\.app$"
)


def _request(peer: str = PEER, **headers: str) -> StarletteRequest:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw,
        "client": (peer, 50000),
        "server": ("test", 80),
    }
    return StarletteRequest(scope)


def _use_secret(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(settings, "vercel_proxy_secret", SecretStr(value))


class TestCorsSettings:
    def test_allowed_origins_alias_and_blank_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000")
        created = Settings(_env_file=None)
        assert created.allowed_origins_list == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
        assert created.cors_origin_regex is None

        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "   ")
        blank = Settings(_env_file=None)
        assert blank.allowed_origins_list == created.allowed_origins_list

    def test_cors_allowed_origins_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://sports-lab.vercel.app")
        monkeypatch.setenv("CORS_ALLOWED_ORIGIN_REGEX", PREVIEW_REGEX)
        created = Settings(_env_file=None)
        assert created.allowed_origins_list == ["https://sports-lab.vercel.app"]
        assert created.cors_origin_regex == PREVIEW_REGEX
        kwargs = created.cors_middleware_kwargs()
        assert kwargs["allow_origins"] == ["https://sports-lab.vercel.app"]
        assert kwargs["allow_origin_regex"] == PREVIEW_REGEX

    @pytest.mark.parametrize(
        "env_name,value",
        [
            ("ALLOWED_ORIGINS", "*"),
            ("CORS_ALLOWED_ORIGINS", "https://sports-lab.vercel.app, *"),
            ("CORS_ALLOWED_ORIGINS", "https://*.vercel.app"),
        ],
    )
    def test_star_origin_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, env_name: str, value: str
    ) -> None:
        monkeypatch.setenv(env_name, value)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    @pytest.mark.parametrize("pattern", ["*", ".*", "^https://.*$", "https://evil.example"])
    def test_open_origin_regex_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, pattern: str
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGIN_REGEX", pattern)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_app_middleware_uses_settings_cors(self) -> None:
        from fastapi.middleware.cors import CORSMiddleware

        found = [item for item in app.user_middleware if item.cls is CORSMiddleware]
        assert len(found) == 1
        assert found[0].kwargs["allow_origins"] == settings.allowed_origins_list
        assert found[0].kwargs["allow_origin_regex"] == settings.cors_origin_regex
        assert "*" not in found[0].kwargs["allow_origins"]


class TestAgentChatDeadline:
    def test_timeout_returns_504(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.api import agent_deadline

        async def slow(_request: AgentChatRequest):
            await asyncio.sleep(1)
            raise AssertionError("the deadline should have cancelled this")

        monkeypatch.setattr(agent_deadline.agent_chat_service, "handle_chat", slow)
        monkeypatch.setattr(settings, "agent_chat_timeout_seconds", 0.05)

        with TestClient(app) as client:
            nba = client.post("/api/nba/agent/chat", json={"message": "hi", "action": "general"})
            wnba = client.post("/api/wnba/agent/chat", json={"message": "hi", "action": "general"})

        for response in (nba, wnba):
            assert response.status_code == 504
            detail = response.json()["detail"]
            assert "time limit" in detail
            assert "120s" in detail

    def test_run_agent_chat_returns_the_service_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.api import agent_deadline
        from app.models.agent_chat import AgentChatResponse

        async def fast(request: AgentChatRequest) -> AgentChatResponse:
            return AgentChatResponse(
                thread=request.thread,
                action=request.action,
                status="error",
                reply="done",
            )

        monkeypatch.setattr(agent_deadline.agent_chat_service, "handle_chat", fast)
        result = asyncio.run(run_agent_chat(AgentChatRequest(message="hi")))
        assert result.reply == "done"


class TestEventStreamCacheControl:
    def test_sse_gets_cache_control_and_json_does_not(self) -> None:
        mini = FastAPI()
        mini.add_middleware(EventStreamCacheControlMiddleware)

        @mini.get("/stream")
        def stream():
            return StreamingResponse(iter([b"data: hi\n\n"]), media_type="text/event-stream")

        @mini.get("/json")
        def document():
            return {"ok": True}

        with TestClient(mini) as client:
            streamed = client.get("/stream")
            body = client.get("/json")

        assert streamed.headers["cache-control"] == "no-cache, no-transform"
        assert body.headers.get("cache-control") != "no-cache, no-transform"


class TestProxyRateLimitKey:
    def test_production_limiter_uses_the_custom_key(self) -> None:
        assert limiter._key_func is client_address_key
        assert PROXY_SECRET_HEADER == "x-sportslab-proxy-secret"

    def test_spoofed_headers_without_secret_use_the_peer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(**{"x-real-ip": "203.0.113.8", "x-forwarded-for": "203.0.113.8"})
        assert client_address_key(request) == PEER

    def test_wrong_secret_uses_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: "wrong-secret",
                "x-real-ip": "203.0.113.8",
                "x-forwarded-for": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER

    def test_valid_secret_uses_x_real_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "203.0.113.8",
                "x-forwarded-for": "198.51.100.20",
            }
        )
        assert client_address_key(request) == "203.0.113.8"

    def test_valid_secret_with_only_xff_uses_the_left_most(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-forwarded-for": " 203.0.113.7 , 198.51.100.20",
            }
        )
        assert client_address_key(request) == "203.0.113.7"

    def test_garbage_ip_uses_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "not-an-ip",
                "x-forwarded-for": "also-bad, 999.1.1.1",
            }
        )
        assert client_address_key(request) == PEER

    def test_garbage_real_ip_falls_back_to_xff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "not-an-ip",
                "x-forwarded-for": "203.0.113.15, 198.51.100.20",
            }
        )
        assert client_address_key(request) == "203.0.113.15"

    def test_empty_secret_never_trusts_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, "")
        request = _request(
            **{
                PROXY_SECRET_HEADER: "",
                "x-real-ip": "203.0.113.8",
                "x-forwarded-for": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER

    def test_empty_header_with_a_configured_secret_uses_the_peer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: "",
                "x-real-ip": "203.0.113.8",
                "x-forwarded-for": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER

    def test_whitespace_only_header_uses_the_peer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: "   ",
                "x-real-ip": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER

    def test_different_length_secret_uses_the_peer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: "short",
                "x-real-ip": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER

    def test_valid_secret_accepts_ipv6_real_ip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "2001:db8::1",
            }
        )
        assert client_address_key(request) == "2001:db8::1"
        bracketed = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "[2001:db8::2]",
            }
        )
        assert client_address_key(bracketed) == "2001:db8::2"

    def test_valid_secret_accepts_ipv6_xff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-forwarded-for": " 2001:db8::8 , 198.51.100.20",
            }
        )
        assert client_address_key(request) == "2001:db8::8"

    def test_two_real_ips_do_not_share_a_bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        mini = FastAPI()
        mini_limiter = Limiter(
            key_func=client_address_key,
            default_limits=[],
            storage_uri="memory://",
        )
        mini.state.limiter = mini_limiter

        @mini.exception_handler(RateLimitExceeded)
        def _limited(_request: Request, _exc: RateLimitExceeded):
            return PlainTextResponse("limited", status_code=429)

        @mini.get("/ping")
        @mini_limiter.limit("1/minute")
        def ping(request: Request):
            return {"ok": True, "key": client_address_key(request)}

        mini.add_middleware(SlowAPIMiddleware)

        def headers_for(ip: str) -> dict[str, str]:
            return {PROXY_SECRET_HEADER: SECRET, "x-real-ip": ip}

        with TestClient(mini) as client:
            first = client.get("/ping", headers=headers_for("203.0.113.10"))
            again = client.get("/ping", headers=headers_for("203.0.113.10"))
            other = client.get("/ping", headers=headers_for("203.0.113.20"))

        assert first.status_code == 200
        assert again.status_code == 429
        assert other.status_code == 200
        assert first.json()["key"] == "203.0.113.10"
        assert other.json()["key"] == "203.0.113.20"

    def test_missing_header_uses_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        assert client_address_key(_request()) == PEER

    def test_blank_header_uses_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(**{PROXY_SECRET_HEADER: "   ", "x-real-ip": "203.0.113.8"})
        assert client_address_key(request) == PEER

    def test_longer_secret_uses_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET + "-extra",
                "x-real-ip": "203.0.113.8",
            }
        )
        assert client_address_key(request) == PEER

    def test_padded_secret_matches_the_trimmed_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, f"  {SECRET}  ")
        request = _request(
            **{
                PROXY_SECRET_HEADER: f"\t{SECRET}\n",
                "x-real-ip": "203.0.113.8",
            }
        )
        assert client_address_key(request) == "203.0.113.8"

    def test_valid_secret_uses_ipv6_real_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-real-ip": "[2001:db8::1]",
                "x-forwarded-for": "203.0.113.8",
            }
        )
        assert client_address_key(request) == "2001:db8::1"

    def test_valid_secret_with_only_ipv6_xff_uses_the_left_most(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_secret(monkeypatch, SECRET)
        request = _request(
            **{
                PROXY_SECRET_HEADER: SECRET,
                "x-forwarded-for": "2001:db8::2, 203.0.113.8",
            }
        )
        assert client_address_key(request) == "2001:db8::2"


def _gated_app() -> FastAPI:
    mini = FastAPI()

    @mini.get("/api/health")
    def health():
        return {"ok": True}

    @mini.get("/health")
    def short_health():
        return {"ok": True}

    @mini.get("/api/ping")
    def ping():
        return {"ok": True}

    @mini.options("/api/ping")
    def options_ping():
        return {"ok": True}

    @mini.get("/api/stream")
    def stream():
        return StreamingResponse(iter([b"data: hi\n\n"]), media_type="text/event-stream")

    mini.add_middleware(ProxySecretMiddleware)
    return mini


class TestProxySecretRequired:
    def test_defaults_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PROXY_SECRET_REQUIRED", raising=False)
        created = Settings(_env_file=None)
        assert created.proxy_secret_required is False

    def test_off_allows_a_request_without_the_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "proxy_secret_required", False)
        with TestClient(_gated_app()) as client:
            response = client.get("/api/ping")
        assert response.status_code == 200

    def test_on_rejects_missing_wrong_and_blank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "proxy_secret_required", True)
        _use_secret(monkeypatch, SECRET)
        with TestClient(_gated_app()) as client:
            missing = client.get("/api/ping")
            blank = client.get("/api/ping", headers={PROXY_SECRET_HEADER: "  "})
            wrong = client.get("/api/ping", headers={PROXY_SECRET_HEADER: "nope"})
            ok = client.get("/api/ping", headers={PROXY_SECRET_HEADER: SECRET})
        assert missing.status_code == 403
        assert blank.status_code == 403
        assert wrong.status_code == 403
        assert missing.json()["detail"] == "A valid proxy secret is required."
        assert SECRET not in missing.text
        assert "nope" not in wrong.text
        assert ok.status_code == 200

    def test_health_stays_open_without_the_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "proxy_secret_required", True)
        _use_secret(monkeypatch, SECRET)
        with TestClient(_gated_app()) as client:
            api_health = client.get("/api/health")
            short = client.get("/health")
            ping = client.get("/api/ping")
        assert api_health.status_code == 200
        assert short.status_code == 200
        assert ping.status_code == 403

    def test_options_and_sse_require_the_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "proxy_secret_required", True)
        _use_secret(monkeypatch, SECRET)
        with TestClient(_gated_app()) as client:
            options = client.options("/api/ping")
            streamed = client.get("/api/stream")
            allowed = client.get("/api/stream", headers={PROXY_SECRET_HEADER: SECRET})
        assert options.status_code == 403
        assert streamed.status_code == 403
        assert allowed.status_code == 200
        assert allowed.headers["content-type"].startswith("text/event-stream")

    def test_required_without_a_secret_refuses_to_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PROXY_SECRET_REQUIRED", "true")
        monkeypatch.setenv("VERCEL_PROXY_SECRET", "   ")
        with pytest.raises(ValidationError, match="PROXY_SECRET_REQUIRED"):
            Settings(_env_file=None)

    def test_loaded_secret_strips_surrounding_whitespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VERCEL_PROXY_SECRET", f"  {SECRET} \n")
        created = Settings(_env_file=None)
        assert created.vercel_proxy_secret.get_secret_value() == SECRET

    def test_trailing_slash_is_still_health(self) -> None:
        assert _is_health_path("/api/health/")
        assert _is_health_path("/health")
        assert not _is_health_path("/api/healthcheck")

    def test_prod_compose_leaves_the_flag_off(self) -> None:
        text = (REPO / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8")
        assert 'PROXY_SECRET_REQUIRED: "false"' in text


class TestPullSsmEnv:
    def _aws(self, tmp_path: Path, body: str, code: int = 0) -> Path:
        path = tmp_path / "aws"
        path.write_text(
            f"#!/bin/sh\ncat > \"{tmp_path / 'aws-args'}\" <<'ARGS'\n\"$@\"\nARGS\n"
            f"printf '%s' '{body}'\nexit {code}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def test_writes_env_file_without_printing_values(self, tmp_path: Path) -> None:
        secret = "db-password-value"
        token = "ghcr-token-value"
        page1 = json.loads(SSM_PAGE1)
        page2 = json.loads(SSM_PAGE2)
        assert page1["Parameters"][0]["Value"] == secret
        assert page1["Parameters"][2]["Value"] == token
        assert page2["Parameters"][0]["Value"] == "sk-test-value"
        values = {
            item["Name"].rsplit("/", 1)[-1]: item["Value"]
            for item in [*page1["Parameters"], *page2["Parameters"]]
        }
        page1_path = tmp_path / "page1.json"
        page2_path = tmp_path / "page2.json"
        page1_path.write_text(SSM_PAGE1, encoding="utf-8")
        page2_path.write_text(SSM_PAGE2, encoding="utf-8")
        aws = tmp_path / "aws"
        aws.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" >> \"{tmp_path / 'aws-args'}\"\n"
            "if printf '%s\\n' \"$@\" | grep -q -- '--next-token'; then\n"
            f"  cat \"{page2_path}\"\n"
            "else\n"
            f"  cat \"{page1_path}\"\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        aws.chmod(0o755)
        dest = tmp_path / "backend.env"
        ghcr = tmp_path / "ghcr.env"
        result = subprocess.run(
            [str(PULL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AWS_CLI": str(aws),
                "SPORTSLAB_ENV_FILE": str(dest),
                "SPORTSLAB_GHCR_ENV_FILE": str(ghcr),
                "SSM_PREFIX": "/sportslab/prod/",
                "AWS_REGION": "us-east-2",
            },
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert secret not in combined
        assert token not in combined
        assert values["OPENAI_API_KEY"] not in combined
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600
        assert stat.S_IMODE(ghcr.stat().st_mode) == 0o600
        text = dest.read_text(encoding="utf-8")
        assert f"DATABASE_URL={secret}\n" in text
        assert f"OPENAI_API_KEY={values['OPENAI_API_KEY']}\n" in text
        assert "GHCR_PULL_TOKEN" not in text
        assert ghcr.read_text(encoding="utf-8") == (
            f"GHCR_PULL_USER={values['GHCR_PULL_USER']}\n"
            f"GHCR_PULL_TOKEN={token}\n"
        )
        assert "--next-token" in (tmp_path / "aws-args").read_text(encoding="utf-8")

    def test_aws_failure_does_not_print_stderr(self, tmp_path: Path) -> None:
        secret = "should-not-leak"
        aws = self._aws(tmp_path, "", code=1)
        aws.write_text(
            f"#!/bin/sh\necho 'failed {secret}' >&2\nexit 1\n",
            encoding="utf-8",
        )
        aws.chmod(0o755)
        dest = tmp_path / "backend.env"
        result = subprocess.run(
            [str(PULL_SCRIPT)],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AWS_CLI": str(aws),
                "SPORTSLAB_ENV_FILE": str(dest),
                "SSM_PREFIX": "/sportslab/prod/",
            },
        )
        assert result.returncode != 0
        assert secret not in result.stdout + result.stderr
        assert "ssm get-parameters-by-path failed" in result.stderr
        assert not dest.exists()


def _caddy_sites(text: str) -> list[tuple[str, str]]:
    """Top-level site blocks. The global options block is not a site."""
    lines = text.splitlines()
    sites: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if stripped == "{":
            depth = 1
            index += 1
            while index < len(lines) and depth:
                depth += lines[index].count("{") - lines[index].count("}")
                index += 1
            continue
        if stripped.endswith("{"):
            address = stripped[:-1].strip()
            body: list[str] = []
            depth = 1
            index += 1
            while index < len(lines) and depth:
                depth += lines[index].count("{") - lines[index].count("}")
                if depth:
                    body.append(lines[index])
                index += 1
            sites.append((address, "\n".join(body)))
            continue
        index += 1
    return sites


class TestHttpsCaddy:
    def test_rendered_caddyfile_redirects_http_and_proxies_https(self) -> None:
        host = "203-0-113-10.sslip.io"
        raw = (REPO / "deploy" / "Caddyfile.https").read_text(encoding="utf-8")
        rendered = raw.replace("{$DOMAIN}", host)
        assert host in rendered
        assert "flush_interval -1" in rendered
        assert "read_timeout 125s" in rendered
        sites = _caddy_sites(rendered)
        assert [address for address, _body in sites] == [host, f"http://{host}"]
        https_body = sites[0][1]
        redirect_body = sites[1][1]
        assert "reverse_proxy backend:8000" in https_body
        assert "redir" in redirect_body
        assert "reverse_proxy" not in redirect_body
        http_sites = [address for address, _body in sites if address.startswith("http://")]
        assert http_sites == [f"http://{host}"]

    def test_entrypoint_refuses_plain_http(self) -> None:
        text = (REPO / "deploy" / "caddy-entrypoint.sh").read_text(encoding="utf-8")
        assert "Caddyfile.https" in text
        assert "DOMAIN is empty" in text
        assert "Caddyfile --adapter" not in text

    def test_backend_api_url_is_https(self) -> None:
        outputs = (REPO / "infra" / "aws" / "outputs.tf").read_text(encoding="utf-8")
        ec2 = (REPO / "infra" / "aws" / "ec2.tf").read_text(encoding="utf-8")
        assert 'output "backend_api_url"' in outputs
        assert 'value       = "https://${local.backend_hostname}"' in outputs
        expression = (
            'var.domain != "" ? var.domain : '
            '"${replace(aws_eip.app.public_ip, ".", "-")}.sslip.io"'
        )
        assert expression in ec2
        assert "resource \"aws_eip_association\" \"app\"" in ec2
        eip = ec2.split("resource \"aws_eip\" \"app\"", 1)[1].split("resource ", 1)[0]
        assert "instance" not in eip
        sample = "203.0.113.10"
        hostname = sample.replace(".", "-") + ".sslip.io"
        assert f"https://{hostname}" == "https://203-0-113-10.sslip.io"
        real = "api.example.com"
        chosen = real if real != "" else hostname
        assert chosen == real
        assert f"https://{chosen}" == "https://api.example.com"

    def test_root_health_answers(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestPublicSubnets:
    def test_instance_uses_the_first_sorted_public_subnet(self) -> None:
        ec2 = (REPO / "infra" / "aws" / "ec2.tf").read_text(encoding="utf-8")
        network = (REPO / "infra" / "aws" / "network.tf").read_text(encoding="utf-8")
        indexed = "sort(local.public_subnet_ids)[0]"
        assert f"app_subnet_id = try({indexed}, null)" in ec2
        assert ec2.count(indexed) == 1
        assert "data.aws_subnets" not in ec2
        assert "data.aws_vpc" not in ec2
        assert 'data "aws_subnet" "selected"' in network
        assert "for_each = toset(local.subnet_ids)" in network
        instance = ec2.split('resource "aws_instance" "app"', 1)[1]
        assert (
            "public_subnet_ids is empty. Set vpc_id to a VPC whose subnets "
            "have MapPublicIpOnLaunch=true."
        ) in instance
        group = network.split('resource "aws_db_subnet_group" "this"', 1)[1].split(
            'resource "aws_security_group"', 1
        )[0]
        assert "data.aws_subnet.selected" in group
        assert "availability_zone" in group
        assert ">= 2" in group
        assert 'name        = "${local.name_prefix}-rds"' in group
        assert 'description = "Subnets for ${local.name_prefix} RDS"' in group

    def test_docs_say_a_check_cannot_catch_a_missing_default_vpc(self) -> None:
        for relative in (
            "docs/deployment/aws.md",
            "docs/deployment/aws-steps-zh-TW.md",
            "infra/aws/README.md",
        ):
            text = (REPO / relative).read_text(encoding="utf-8")
            assert "MapPublicIpOnLaunch" in text
            assert "no matching EC2 VPC found" in text
            assert "check" in text.lower()


def test_nba_starts_and_serves_without_odds_api_key() -> None:
    """Process, scheduler, health, and CSV players do not need ODDS_API_KEY."""
    script = r"""
import os
import time

os.environ["ODDS_API_KEY"] = ""
os.environ["BALLDONTLIE_API_KEY"] = ""
os.environ["PROXY_SECRET_REQUIRED"] = "false"
os.environ.pop("SPORTSDATA_API_KEY", None)

from fastapi.testclient import TestClient

from app.main import app
from app.services.scheduler import scheduler_service
from app.settings import settings

assert settings.odds_api_key == ""
with TestClient(app) as client:
    health = client.get("/api/health")
    root = client.get("/health")
    csv_players = client.get("/api/nba/csv/players")
    assert health.status_code == 200, health.status_code
    assert root.status_code == 200, root.status_code
    assert csv_players.status_code == 200, csv_players.status_code
    assert "Invalid API key" not in csv_players.text
    assert scheduler_service.is_running is True
    job_ids = {job.id for job in scheduler_service._scheduler.get_jobs()}
    assert "nba_injuries_refresh" in job_ids
    assert not any("projection" in job_id for job_id in job_ids)
    time.sleep(2)
    again = client.get("/api/health")
    assert again.status_code == 200, again.status_code
print("ok")
"""
    env = os.environ.copy()
    env["ODDS_API_KEY"] = ""
    env["BALLDONTLIE_API_KEY"] = ""
    env["PROXY_SECRET_REQUIRED"] = "false"
    env.pop("SPORTSDATA_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO / "backend",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
