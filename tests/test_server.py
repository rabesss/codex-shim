from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from codex_shim import server as server_module
from codex_shim.server import (
    ResponsesStreamState,
    ShimServer,
    _build_tool_types,
    _current_managed_model,
    _join_url,
    _picker_html,
    _rewrite_response_model,
    _sanitize_chatgpt_passthrough_body,
    _set_active_model,
)
from codex_shim.settings import FALLBACK_CHATGPT_PASSTHROUGH_SLUGS
from codex_shim.translate import SHIM_ENCRYPTED_CONTENT_PREFIX


@pytest.fixture
def auth_present(monkeypatch, tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "stub", "account_id": "acct"}}))
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_AUTH", auth)
    monkeypatch.setattr("codex_shim.server.DEFAULT_CODEX_AUTH", auth)
    monkeypatch.setenv("CODEX_SHIM_ENABLE_CHATGPT", "1")
    return auth


@pytest.fixture
def auth_missing(monkeypatch, tmp_path):
    missing = tmp_path / "missing-auth.json"
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_AUTH", missing)
    monkeypatch.setattr("codex_shim.server.DEFAULT_CODEX_AUTH", missing)


def test_sanitize_chatgpt_passthrough_body_drops_shim_reasoning():
    body = {
        "model": "claude-local",
        "input": [
            {"type": "message", "role": "user", "content": "hi"},
            {
                "id": "rs_shim",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "local thought"}],
                "encrypted_content": f"{SHIM_ENCRYPTED_CONTENT_PREFIX}deadbeef",
            },
            {
                "id": "rs_openai",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "openai thought"}],
                "encrypted_content": "openai-verifiable-content",
            },
        ],
    }

    sanitized = _sanitize_chatgpt_passthrough_body(body)

    assert sanitized is not body
    assert sanitized["input"] is not body["input"]
    assert [item["id"] for item in sanitized["input"] if item.get("type") == "reasoning"] == ["rs_openai"]
    assert sanitized["input"][1]["encrypted_content"] == "openai-verifiable-content"
    assert len(body["input"]) == 3


def test_sanitize_chatgpt_passthrough_body_removes_nested_shim_encrypted_content():
    body = {
        "model": "claude-local",
        "input": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "done",
                        "encrypted_content": f"{SHIM_ENCRYPTED_CONTENT_PREFIX}deadbeef",
                    }
                ],
            }
        ],
    }

    sanitized = _sanitize_chatgpt_passthrough_body(body)

    assert "encrypted_content" not in sanitized["input"][0]["content"][0]
    assert "encrypted_content" in body["input"][0]["content"][0]


def test_rewrite_response_model_only_rewrites_chatgpt_metadata():
    payload = {
        "model": "gpt-5.5",
        "nested": [{"model": "gpt-5.5"}, {"model": "other"}],
    }

    _rewrite_response_model(payload, "custom-model")

    assert payload == {
        "model": "custom-model",
        "nested": [{"model": "custom-model"}, {"model": "other"}],
    }


def test_image_generation_detection_is_conservative():
    shim = ShimServer()
    tools = [
        {"type": "function", "function": {"name": "shell"}},
        {"type": "image_generation", "name": "image_generation"},
    ]

    assert shim._needs_image_gen({"tools": tools, "input": [{"role": "user", "content": "write code for an icon component"}]}) is False
    assert shim._needs_image_gen({"tools": tools, "input": [{"role": "user", "content": "@image generate a neon fox"}]}) is True
    assert shim._needs_image_gen({"tools": tools, "tool_choice": {"type": "image_generation"}, "input": "hi"}) is True
    assert shim._needs_image_followup(
        {
            "input": [
                {"type": "image_generation_call", "id": "ig_1"},
                {"role": "user", "content": "make it brighter"},
            ]
        }
    ) is True


def test_join_url_handles_versioned_provider_bases():
    assert _join_url("https://api.openai.com/v1", "/chat/completions") == "https://api.openai.com/v1/chat/completions"
    assert _join_url("https://api.z.ai/api/coding/paas/v4", "/chat/completions") == (
        "https://api.z.ai/api/coding/paas/v4/chat/completions"
    )
    assert _join_url("https://example.test/api/coding/v3", "/messages") == "https://example.test/api/coding/v3/messages"
    assert _join_url("https://example.test", "/chat/completions") == "https://example.test/v1/chat/completions"


def test_build_tool_types_preserves_native_and_mcp_types():
    body = {
        "tools": [
            {"type": "apply_patch"},
            {"type": "web_search_preview"},
            {"type": "mcp__node_repl", "function": {"name": "js"}},
        ]
    }

    tool_types = _build_tool_types(body)

    assert tool_types["apply_patch"] == "apply_patch"
    assert tool_types["web_search"] == "web_search_preview"
    assert tool_types["mcp__node_repl__js"] == "mcp__node_repl"


async def test_image_generation_routes_to_chatgpt_passthrough_and_rewrites_model(monkeypatch, tmp_path, auth_present):
    captured = {}

    class FakeUpstream:
        status = 200
        content_type = "application/json"

        async def json(self, content_type=None):
            return {"id": "resp_img", "model": "gpt-5.5", "output": [{"type": "image_generation_call", "model": "gpt-5.5"}]}

        def release(self):
            pass

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = headers
        return FakeUpstream()

    monkeypatch.setattr("codex_shim.server.ClientSession.post", fake_post)
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "real-openai",
                        "displayName": "Real OpenAI",
                        "provider": "openai",
                        "baseUrl": "http://example.invalid/v1",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post(
        "/v1/responses",
        json={
            "model": "real-openai",
            "input": [{"role": "user", "content": "@image generate a neon fox"}],
            "tools": [{"type": "image_generation", "name": "image_generation"}],
        },
    )
    assert resp.status == 200
    payload = await resp.json()
    assert payload["model"] == "real-openai"
    assert payload["output"][0]["model"] == "real-openai"
    assert captured["body"]["model"] == "gpt-5.5"
    assert captured["headers"]["Authorization"] == "Bearer stub"

    await shim_client.close()


async def test_image_generation_uses_byok_when_chatgpt_passthrough_disabled(tmp_path, auth_missing):
    captured = {}

    async def chat(request):
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl_fake",
                "choices": [{"message": {"role": "assistant", "content": "no image backend"}}],
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat)
    upstream_client = TestClient(TestServer(upstream))
    await upstream_client.start_server()

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "real-openai",
                        "displayName": "Real OpenAI",
                        "provider": "openai",
                        "baseUrl": str(upstream_client.make_url("/v1")),
                        "apiKey": "secret",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post(
        "/v1/responses",
        json={
            "model": "real-openai",
            "input": [{"role": "user", "content": "@image generate a neon fox"}],
            "tools": [{"type": "image_generation", "name": "image_generation"}],
        },
    )

    assert resp.status == 200
    assert captured["body"]["model"] == "real-openai"
    payload = await resp.json()
    assert payload["output"][0]["content"][0]["text"] == "no image backend"

    await shim_client.close()
    await upstream_client.close()


async def test_responses_routes_to_openai_chat(tmp_path):
    captured = {}

    async def chat(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl_fake",
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat)
    upstream_client = TestClient(TestServer(upstream))
    await upstream_client.start_server()

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "real-openai",
                        "displayName": "Real OpenAI",
                        "provider": "openai",
                        "baseUrl": str(upstream_client.make_url("/v1")),
                        "apiKey": "secret",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post("/v1/responses", json={"model": "real-openai", "input": "hi"})
    assert resp.status == 200
    payload = await resp.json()
    assert payload["output"][0]["content"][0]["text"] == "hello"
    assert payload["usage"] == {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    assert captured["body"]["model"] == "real-openai"
    assert captured["headers"]["Authorization"] == "Bearer secret"

    await shim_client.close()
    await upstream_client.close()


def _sse_events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        if not block.startswith("data:"):
            continue
        data = block.removeprefix("data:").strip()
        if data and data != "[DONE]":
            events.append(json.loads(data))
    return events


async def test_streaming_openai_chat_response_completed_includes_usage(tmp_path):
    async def chat(request):
        await request.json()
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n')
        await response.write(
            b'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6,"prompt_tokens_details":{"cached_tokens":3}}}\n\n'
        )
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat)
    upstream_client = TestClient(TestServer(upstream))
    await upstream_client.start_server()

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "real-openai",
                        "displayName": "Real OpenAI",
                        "provider": "openai",
                        "baseUrl": str(upstream_client.make_url("/v1")),
                        "apiKey": "secret",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post("/v1/responses", json={"model": "real-openai", "input": "hi", "stream": True})
    assert resp.status == 200
    events = _sse_events(await resp.text())
    completed = [event for event in events if event.get("type") == "response.completed"][-1]
    assert completed["response"]["usage"] == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
        "input_tokens_details": {"cached_tokens": 3},
    }

    await shim_client.close()
    await upstream_client.close()


async def test_streaming_openai_chat_delta_strips_think_blocks():
    class FakeResponse:
        def __init__(self):
            self.chunks: list[bytes] = []

        async def write(self, data: bytes):
            self.chunks.append(data)

    downstream = FakeResponse()
    state = ResponsesStreamState("minimax-coding")
    for text in ["Visible <thi", "nk>secret", "</thi", "nk> final"]:
        await state.write_chat_delta(
            downstream,
            {"choices": [{"delta": {"content": text}}]},
        )
    await state.finish(downstream)

    raw = b"".join(downstream.chunks).decode()
    events = _sse_events(raw)
    deltas = [event["delta"] for event in events if event.get("type") == "response.output_text.delta"]
    completed = [event for event in events if event.get("type") == "response.completed"][-1]

    assert deltas == ["Visible ", " final"]
    assert completed["response"]["output"][0]["content"][0]["text"] == "Visible  final"
    assert "<think>" not in raw
    assert "secret" not in raw


async def test_streaming_openai_error_frame_emits_failed_response():
    class FakeResponse:
        def __init__(self):
            self.chunks: list[bytes] = []

        async def write(self, data: bytes):
            self.chunks.append(data)

    downstream = FakeResponse()
    state = ResponsesStreamState("real-openai")

    await state.start(downstream)
    await state.fail(downstream, {"message": "rate limited", "code": "rate_limit"})

    events = _sse_events(b"".join(downstream.chunks).decode())
    assert [event.get("type") for event in events] == ["response.created", "response.failed"]
    assert events[-1]["response"]["status"] == "failed"
    assert events[-1]["response"]["error"]["message"] == "rate limited"


async def test_streaming_tool_item_type_and_namespace_are_restored():
    class FakeResponse:
        def __init__(self):
            self.chunks: list[bytes] = []

        async def write(self, data: bytes):
            self.chunks.append(data)

    downstream = FakeResponse()
    state = ResponsesStreamState(
        "real-openai",
        {"mcp__codex_apps__github__get_repo": ("mcp__codex_apps__github", "get_repo")},
        {"apply_patch": "apply_patch", "mcp__codex_apps__github__get_repo": "mcp__codex_apps__github__get_repo"},
    )
    await state.start(downstream)
    await state.write_chat_delta(
        downstream,
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call_1", "function": {"name": "apply_patch", "arguments": "diff"}},
                            {"index": 1, "id": "call_2", "function": {"name": "mcp__codex_apps__github__get_repo", "arguments": "{}"}},
                        ]
                    }
                }
            ]
        },
    )
    await state.finish(downstream)

    events = _sse_events(b"".join(downstream.chunks).decode())
    completed = [event for event in events if event.get("type") == "response.completed"][-1]
    assert completed["response"]["output"][0]["type"] == "custom_tool_call"
    assert completed["response"]["output"][1]["namespace"] == "mcp__codex_apps__github"
    assert completed["response"]["output"][1]["name"] == "get_repo"


async def test_streaming_anthropic_response_completed_includes_usage():
    class FakeResponse:
        def __init__(self):
            self.chunks: list[bytes] = []

        async def write(self, data: bytes):
            self.chunks.append(data)

    downstream = FakeResponse()
    state = ResponsesStreamState("claude-real")
    await state.write_anthropic_delta(
        downstream,
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 5,
                    "cache_read_input_tokens": 4,
                    "output_tokens": 1,
                }
            },
        },
    )
    await state.write_anthropic_delta(
        downstream,
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 3},
        },
    )
    await state.finish(downstream)

    events = _sse_events(b"".join(downstream.chunks).decode())
    completed = [event for event in events if event.get("type") == "response.completed"][-1]
    assert completed["response"]["usage"] == {
        "input_tokens": 5,
        "output_tokens": 3,
        "total_tokens": 8,
        "input_tokens_details": {
            "cached_tokens": 4,
            "cache_read_input_tokens": 4,
        },
    }


async def test_responses_compact_routes_to_openai_chat_and_returns_compacted_window(tmp_path):
    captured = {}

    async def chat(request):
        captured["body"] = await request.json()
        return web.json_response(
            {
                "id": "chatcmpl_compact",
                "choices": [{"message": {"role": "assistant", "content": "Task: keep implementing compact support."}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
            }
        )

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat)
    upstream_client = TestClient(TestServer(upstream))
    await upstream_client.start_server()

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "real-openai",
                        "displayName": "Real OpenAI",
                        "provider": "openai",
                        "baseUrl": str(upstream_client.make_url("/v1")),
                        "apiKey": "secret",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post(
        "/v1/responses/compact",
        json={
            "model": "real-openai",
            "input": [
                {"role": "user", "content": "implement compact"},
                {"type": "function_call_output", "call_id": "call_1", "output": "tests pass"},
            ],
            "service_tier": "priority",
            "stream": True,
        },
    )
    assert resp.status == 200
    payload = await resp.json()
    assert payload["status"] == "completed"
    assert payload["model"] == "real-openai"
    assert payload["output"][0]["content"][0]["text"] == "Task: keep implementing compact support."
    assert payload["usage"] == {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11}
    assert captured["body"]["model"] == "real-openai"
    assert captured["body"]["stream"] is False
    assert "service_tier" not in captured["body"]
    assert "Compact the conversation" in captured["body"]["messages"][0]["content"]

    await shim_client.close()
    await upstream_client.close()


async def test_responses_compact_chatgpt_passthrough_uses_compact_endpoint(monkeypatch, tmp_path, auth_present):
    captured = {}

    class FakeUpstream:
        status = 200
        content_type = "application/json"

        async def json(self, content_type=None):
            return {"id": "resp_compact", "model": "gpt-5.5", "output": [{"type": "message", "model": "gpt-5.5"}]}

        def release(self):
            pass

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = headers
        return FakeUpstream()

    monkeypatch.setattr("codex_shim.server.ClientSession.post", fake_post)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post("/v1/responses/compact", json={"model": "openai-gpt-5-5-codex-max", "input": "hi", "stream": True})
    assert resp.status == 200
    payload = await resp.json()
    assert payload["model"] == "openai-gpt-5-5-codex-max"
    assert payload["output"][0]["model"] == "openai-gpt-5-5-codex-max"
    assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses/compact"
    assert captured["body"]["model"] == "gpt-5.5"
    assert "stream" not in captured["body"]
    assert captured["headers"]["Accept"] == "application/json"

    await shim_client.close()


async def test_health_and_models_include_chatgpt_passthrough_when_auth_present(tmp_path, auth_present, monkeypatch):
    missing_cache = tmp_path / "missing-models-cache.json"
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_MODELS_CACHE", missing_cache)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    health = await shim_client.get("/health")
    assert health.status == 200
    body = await health.json()
    assert body["models"] == len(FALLBACK_CHATGPT_PASSTHROUGH_SLUGS)
    assert body["chatgpt_passthrough"] is True

    models = await shim_client.get("/v1/models")
    assert models.status == 200
    payload = await models.json()
    assert sorted(model["id"] for model in payload["data"]) == sorted(FALLBACK_CHATGPT_PASSTHROUGH_SLUGS)

    await shim_client.close()


async def test_health_and_models_hide_chatgpt_passthrough_when_auth_missing(tmp_path, auth_missing):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    health = await shim_client.get("/health")
    body = await health.json()
    assert body["models"] == 0
    assert body["chatgpt_passthrough"] is False

    models = await shim_client.get("/v1/models")
    payload = await models.json()
    assert payload["data"] == []

    await shim_client.close()


@pytest.fixture
def cursor_present(monkeypatch):
    def _on(**_kwargs):
        return True

    for target in (
        "codex_shim.cursor_passthrough.cursor_passthrough_available",
        "codex_shim.server.cursor_passthrough_available",
        "codex_shim.catalog.cursor_passthrough_available",
        "codex_shim.cli.cursor_passthrough_available",
    ):
        monkeypatch.setattr(target, _on)


@pytest.fixture
def cursor_missing(monkeypatch):
    monkeypatch.setattr("codex_shim.cursor_passthrough.cursor_passthrough_available", lambda **_: False)
    monkeypatch.setattr("codex_shim.server.cursor_passthrough_available", lambda **_: False)
    monkeypatch.setattr("codex_shim.catalog.cursor_passthrough_available", lambda **_: False)


async def test_health_and_models_include_cursor_passthrough_when_auth_present(tmp_path, cursor_present, auth_missing):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    health = await shim_client.get("/health")
    assert health.status == 200
    body = await health.json()
    assert body["models"] == 1
    assert body["cursor_passthrough"] is True

    models = await shim_client.get("/v1/models")
    payload = await models.json()
    assert [model["id"] for model in payload["data"]] == ["composer-2-5"]

    await shim_client.close()


async def test_health_and_models_hide_cursor_passthrough_when_auth_missing(tmp_path, cursor_missing, auth_missing):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    health = await shim_client.get("/health")
    body = await health.json()
    assert body["models"] == 0
    assert body["cursor_passthrough"] is False

    models = await shim_client.get("/v1/models")
    payload = await models.json()
    assert payload["data"] == []

    await shim_client.close()


async def test_chat_routes_to_openai_normalizes_developer_role(tmp_path):
    captured = {}

    async def chat(request):
        captured["body"] = await request.json()
        return web.json_response({"id": "chatcmpl_fake", "choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", chat)
    upstream_client = TestClient(TestServer(upstream))
    await upstream_client.start_server()

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "deepseek-reasoner",
                        "displayName": "DeepSeek Reasoner",
                        "provider": "openai",
                        "baseUrl": str(upstream_client.make_url("/v1")),
                        "apiKey": "secret",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post(
        "/v1/chat/completions",
        json={"model": "deepseek-reasoner", "messages": [{"role": "developer", "content": "rules"}, {"role": "user", "content": "hi"}]},
    )
    assert resp.status == 200
    assert [message["role"] for message in captured["body"]["messages"]] == ["system", "user"]

    await shim_client.close()
    await upstream_client.close()


async def test_chat_routes_to_anthropic(tmp_path):
    captured = {}

    async def messages(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response({"id": "msg_fake", "content": [{"type": "text", "text": "anthropic hello"}], "stop_reason": "end_turn"})

    upstream = web.Application()
    upstream.router.add_post("/v1/messages", messages)
    upstream_client = TestClient(TestServer(upstream))
    await upstream_client.start_server()

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "claude-real",
                        "displayName": "Claude Real",
                        "provider": "anthropic",
                        "baseUrl": str(upstream_client.make_url("")),
                        "apiKey": "secret",
                    }
                ]
            }
        )
    )
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()

    resp = await shim_client.post("/v1/chat/completions", json={"model": "claude-real", "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status == 200
    payload = await resp.json()
    assert payload["choices"][0]["message"]["content"] == "anthropic hello"
    assert captured["body"]["model"] == "claude-real"
    assert captured["headers"]["x-api-key"] == "secret"
    assert "Authorization" not in captured["headers"]

    await shim_client.close()
    await upstream_client.close()


def _picker_settings_file(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "model": "kimi-k26",
                        "displayName": "Kimi K2.6",
                        "provider": "openai",
                        "baseUrl": "http://example.invalid/v1",
                        "apiKey": "k",
                        "supports_tools": True,
                    },
                    {
                        "model": "deepseek-v4-pro",
                        "displayName": "DeepSeek V4 Pro",
                        "providerDisplayName": "CLIProxyAPI / CommandCode",
                        "provider": "openai",
                        "baseUrl": "http://example.invalid/v1",
                        "apiKey": "k",
                        "supports_tools": True,
                    },
                ]
            }
        )
    )
    return settings


def _stub_codex_config(monkeypatch, tmp_path, *, model: str = "kimi-k26") -> "Path":
    config = tmp_path / "config.toml"
    config.write_text(
        f'model = "{model}"\n'
        'model_provider = "codex_shim"\n'
        '\n'
        '[model_providers.codex_shim]\n'
        'name = "Codex Shim"\n'
        'base_url = "http://127.0.0.1:8765/v1"\n'
        'wire_api = "responses"\n'
    )
    monkeypatch.setattr(server_module, "CODEX_CONFIG_PATH", config)
    return config


def _duplicate_picker_settings_file(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {
                        "slug": "nous-step-flash-a",
                        "model": "nous-a/step-3.7-flash-free",
                        "displayName": "Step 3.7 Flash:free",
                        "providerDisplayName": "Nous Portal",
                        "provider": "openai",
                        "baseUrl": "http://example.invalid/v1",
                        "apiKey": "sk-secret-a",
                    },
                    {
                        "slug": "nous-step-flash-b",
                        "model": "nous-b/step-3.7-flash-free",
                        "displayName": "Step 3.7 Flash:free",
                        "providerDisplayName": "Nous Portal",
                        "provider": "openai",
                        "baseUrl": "http://example.invalid/v1",
                        "apiKey": "sk-secret-b",
                    },
                ]
            }
        )
    )
    return settings


def test_picker_html_renders_self_contained_page():
    html = _picker_html("test-token")
    assert html.startswith("<!DOCTYPE html>")
    assert "/api/models" in html
    assert "/api/switch" in html
    assert "test-token" in html


def test_current_managed_model_reads_top_level_model(monkeypatch, tmp_path):
    _stub_codex_config(monkeypatch, tmp_path, model="deepseek-v4-pro")
    assert _current_managed_model() == "deepseek-v4-pro"


def test_current_managed_model_returns_none_when_config_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "CODEX_CONFIG_PATH", tmp_path / "nope.toml")
    assert _current_managed_model() is None


def test_set_active_model_rewrites_model_and_provider_name(monkeypatch, tmp_path):
    config = _stub_codex_config(monkeypatch, tmp_path)
    _set_active_model("deepseek-v4-pro", "DeepSeek V4 Pro")
    text = config.read_text()
    assert 'model = "deepseek-v4-pro"' in text
    assert 'name = "DeepSeek V4 Pro"' in text


def test_set_active_model_no_op_when_config_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "CODEX_CONFIG_PATH", tmp_path / "nope.toml")
    # Should not raise.
    _set_active_model("anything", "Anything")


async def test_picker_page_served_at_picker(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get("/picker")
        assert resp.status == 200
        text = await resp.text()
        assert "/api/models" in text
    finally:
        await shim_client.close()


async def test_api_models_lists_configured_models_with_active_flag(
    monkeypatch, tmp_path, auth_missing
):
    settings = _picker_settings_file(tmp_path)
    _stub_codex_config(monkeypatch, tmp_path, model="deepseek-v4-pro")
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get(
            "/api/models", headers={"Origin": "http://127.0.0.1:5175"}
        )
        assert resp.status == 200
        assert resp.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5175"
        assert resp.headers["Access-Control-Allow-Methods"] == "GET, OPTIONS"
        assert resp.headers["Access-Control-Allow-Private-Network"] == "true"
        data = await resp.json()
        slugs = [m["slug"] for m in data]
        assert slugs == ["kimi-k26", "deepseek-v4-pro"]
        active = {m["slug"]: m["active"] for m in data}
        assert active == {"kimi-k26": False, "deepseek-v4-pro": True}
        deepseek = data[1]
        assert deepseek["model"] == "deepseek-v4-pro"
        assert deepseek["display_name"] == "DeepSeek V4 Pro"
        assert deepseek["provider_display_name"] == "CLIProxyAPI / CommandCode"
        assert deepseek["model_provider"] == "codex_shim"
        assert deepseek["owned_by"] == "codex_shim"
        assert "model_catalog_json" not in deepseek
        assert deepseek["input_modalities"] == ["text", "image"]
        assert deepseek["supports_tools"] is True
        assert deepseek["supports_reasoning"] is True
        assert deepseek["upstream_model_id"] == "deepseek-v4-pro"
        assert "api_key" not in json.dumps(deepseek).lower()
    finally:
        await shim_client.close()


async def test_api_models_answers_browser_preflight(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.options(
            "/api/models",
            headers={
                "Origin": "http://127.0.0.1:5175",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        assert resp.status == 204
        assert resp.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5175"
        assert resp.headers["Access-Control-Allow-Methods"] == "GET, OPTIONS"
        assert resp.headers["Access-Control-Allow-Private-Network"] == "true"
    finally:
        await shim_client.close()


async def test_api_models_rejects_untrusted_browser_origin(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.options(
            "/api/models",
            headers={
                "Origin": "https://example.test",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        assert resp.status == 204
        assert "Access-Control-Allow-Origin" not in resp.headers
        assert "Access-Control-Allow-Private-Network" not in resp.headers
    finally:
        await shim_client.close()


async def test_api_models_rejects_malformed_loopback_origins(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        for origin in [
            "http://127.0.0.1",
            "http://localhost",
            "http://127.0.0.1:34567/path",
            "http://127.0.0.1:34567?query=1",
            "http://user@127.0.0.1:34567",
            "http://127.0.0.1:99999",
            "null",
        ]:
            resp = await shim_client.options(
                "/api/models",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Private-Network": "true",
                },
            )
            assert resp.status == 204
            assert "Access-Control-Allow-Origin" not in resp.headers
            assert "Access-Control-Allow-Private-Network" not in resp.headers
    finally:
        await shim_client.close()


async def test_api_models_allows_desktop_loopback_origin_port(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get(
            "/api/models", headers={"Origin": "http://127.0.0.1:34567"}
        )
        assert resp.status == 200
        assert resp.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:34567"
        assert resp.headers["Access-Control-Allow-Private-Network"] == "true"
    finally:
        await shim_client.close()


async def test_api_models_dedupes_duplicate_picker_labels(tmp_path, auth_missing):
    settings = _duplicate_picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get("/api/models")
        assert resp.status == 200
        data = await resp.json()
        picker_keys = [
            (m["provider_display_name"], m["display_name"])
            for m in data
            if m["provider_display_name"] == "Nous Portal"
        ]
        assert picker_keys == [("Nous Portal", "Step 3.7 Flash:free")]
        serialized = json.dumps(data)
        assert "api_key" not in serialized.lower()
        assert "sk-" not in serialized.lower()
    finally:
        await shim_client.close()


async def test_api_models_keeps_active_duplicate_picker_label(
    monkeypatch, tmp_path, auth_missing
):
    settings = _duplicate_picker_settings_file(tmp_path)
    _stub_codex_config(monkeypatch, tmp_path, model="nous-step-flash-b")
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get("/api/models")
        assert resp.status == 200
        data = await resp.json()
        nous_rows = [
            m for m in data if m["provider_display_name"] == "Nous Portal"
        ]
        assert len(nous_rows) == 1
        assert nous_rows[0]["slug"] == "nous-step-flash-b"
        assert nous_rows[0]["active"] is True
    finally:
        await shim_client.close()


def test_request_body_dumps_are_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "DEBUG_DIR", tmp_path)
    monkeypatch.delenv("CODEX_SHIM_DEBUG_DUMP_REQUESTS", raising=False)

    server_module._dump_incoming_request("/v1/responses", {"secret": "not-written"})
    server_module._dump_debug_request("custom", "http://127.0.0.1", {"secret": "not-written"})

    assert not (tmp_path / "last_incoming_request.json").exists()
    assert not (tmp_path / "last_request.json").exists()


def test_request_body_dumps_are_private_when_explicitly_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "DEBUG_DIR", tmp_path)
    monkeypatch.setenv("CODEX_SHIM_DEBUG_DUMP_REQUESTS", "1")

    server_module._dump_incoming_request("/v1/responses", {"input": []})
    server_module._dump_debug_request("custom", "http://127.0.0.1", {"messages": []})

    for name in ("last_incoming_request.json", "last_request.json"):
        dump_path = tmp_path / name
        assert dump_path.is_file()
        assert dump_path.stat().st_mode & 0o777 == 0o600


async def test_api_models_includes_chatgpt_when_auth_present(
    monkeypatch, tmp_path, auth_present
):
    missing_cache = tmp_path / "missing-models-cache.json"
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_MODELS_CACHE", missing_cache)
    settings = _picker_settings_file(tmp_path)
    _stub_codex_config(monkeypatch, tmp_path, model="gpt-5.5")
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get("/api/models")
        data = await resp.json()
        slugs = [m["slug"] for m in data]
        assert slugs[0] == "gpt-5.5"
        chatgpt = data[0]
        assert chatgpt["active"] is True
        assert chatgpt["model_provider"] == "codex_shim"
        assert chatgpt["provider"] == "chatgpt"
        assert chatgpt["provider_display_name"] == "ChatGPT/OpenAI"
        assert chatgpt["input_modalities"] == ["text", "image"]
        assert chatgpt["supports_tools"] is True
        assert "api_key" not in json.dumps(chatgpt).lower()
    finally:
        await shim_client.close()


async def test_api_models_includes_cursor_passthrough_metadata(
    monkeypatch, tmp_path, cursor_present, auth_missing
):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"customModels": []}))
    _stub_codex_config(monkeypatch, tmp_path, model="composer-2-5")
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.get("/api/models")
        data = await resp.json()
        assert [m["slug"] for m in data] == ["composer-2-5"]
        cursor = data[0]
        assert cursor["active"] is True
        assert cursor["model"] == "composer-2-5"
        assert cursor["model_provider"] == "codex_shim"
        assert cursor["provider"] == "cursor"
        assert cursor["provider_display_name"] == "Cursor"
        assert cursor["source"] == "Cursor subscription"
        assert cursor["input_modalities"] == ["text", "image"]
        assert cursor["supports_tools"] is True
        assert "api_key" not in json.dumps(cursor).lower()
    finally:
        await shim_client.close()


async def test_switch_model_rewrites_config_without_restart(
    monkeypatch, tmp_path, auth_missing
):
    settings = _picker_settings_file(tmp_path)
    config = _stub_codex_config(monkeypatch, tmp_path, model="kimi-k2.6")
    restart_calls = []
    monkeypatch.setattr(server_module, "_restart_codex_app", lambda: restart_calls.append(True))

    shim = ShimServer(settings)
    shim_client = TestClient(TestServer(shim.app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.post(
            "/api/switch",
            json={"slug": "deepseek-v4-pro", "restart_codex": False},
            headers={"X-Codex-Shim-Picker-Token": shim.picker_token},
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload == {"ok": True, "model": "deepseek-v4-pro", "restarted": False}
        text = config.read_text()
        assert 'model = "deepseek-v4-pro"' in text
        assert 'name = "DeepSeek V4 Pro"' in text
        assert restart_calls == []
    finally:
        await shim_client.close()


async def test_switch_model_triggers_restart_when_requested(
    monkeypatch, tmp_path, auth_missing
):
    settings = _picker_settings_file(tmp_path)
    _stub_codex_config(monkeypatch, tmp_path, model="kimi-k2.6")
    restart_calls = []
    monkeypatch.setattr(server_module, "_restart_codex_app", lambda: restart_calls.append(True))

    shim = ShimServer(settings)
    shim_client = TestClient(TestServer(shim.app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.post(
            "/api/switch",
            json={"slug": "deepseek-v4-pro", "restart_codex": True},
            headers={"X-Codex-Shim-Picker-Token": shim.picker_token},
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload["restarted"] is True
        assert restart_calls == [True]
    finally:
        await shim_client.close()


async def test_switch_model_rejects_unknown_slug(monkeypatch, tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    _stub_codex_config(monkeypatch, tmp_path)
    shim = ShimServer(settings)
    shim_client = TestClient(TestServer(shim.app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.post(
            "/api/switch",
            json={"slug": "nope"},
            headers={"X-Codex-Shim-Picker-Token": shim.picker_token},
        )
        assert resp.status == 404
    finally:
        await shim_client.close()


async def test_switch_model_requires_slug(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim = ShimServer(settings)
    shim_client = TestClient(TestServer(shim.app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.post(
            "/api/switch",
            json={},
            headers={"X-Codex-Shim-Picker-Token": shim.picker_token},
        )
        assert resp.status == 400
    finally:
        await shim_client.close()


async def test_switch_model_rejects_requests_without_picker_token(tmp_path, auth_missing):
    settings = _picker_settings_file(tmp_path)
    shim_client = TestClient(TestServer(ShimServer(settings).app()))
    await shim_client.start_server()
    try:
        resp = await shim_client.post("/api/switch", json={"slug": "deepseek-v4-pro"})
        assert resp.status == 403
        assert await resp.json() == {"error": "invalid picker token"}
    finally:
        await shim_client.close()
