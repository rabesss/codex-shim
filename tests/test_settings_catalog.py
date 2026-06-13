from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_shim import cli
from codex_shim.catalog import catalog_entry, write_catalog
from codex_shim.desktop_models import desktop_models_payload, discover_cliproxyapi_models, write_desktop_models
from codex_shim.settings import ModelSettings, chatgpt_passthrough_available, FALLBACK_CHATGPT_PASSTHROUGH_SLUGS


@pytest.fixture
def auth_present(monkeypatch, tmp_path):
    """Point chatgpt_passthrough_available() at a valid stub auth.json."""
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "stub", "account_id": "acct"}}))
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_AUTH", auth)
    monkeypatch.setenv("CODEX_SHIM_ENABLE_CHATGPT", "1")
    return auth


@pytest.fixture
def auth_missing(monkeypatch, tmp_path):
    """Point chatgpt_passthrough_available() at a path that does not exist."""
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_AUTH", tmp_path / "missing-auth.json")


def test_duplicate_models_get_unique_display_slugs(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {"model": "gpt-5.5", "display_name": "Fast High", "provider": "openai", "base_url": "http://x/v1", "index": 1},
                    {"model": "gpt-5.5", "display_name": "Fast Low", "provider": "openai", "base_url": "http://x/v1", "index": 2},
                ]
            }
        )
    )
    models = ModelSettings(settings).load()
    assert [m.slug for m in models] == ["fast-high", "fast-low"]


def test_legacy_custom_models_schema_still_loads(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "customModels": [
                    {"model": "legacy-model", "displayName": "Legacy Model", "provider": "openai", "baseUrl": "http://x/v1"}
                ]
            }
        )
    )
    [model] = ModelSettings(settings).load()
    assert model.slug == "legacy-model"
    assert model.display_name == "Legacy Model"
    assert model.base_url == "http://x/v1"


def test_ollama_launch_models_schema_loads(tmp_path):
    settings = tmp_path / "ollama-launch-models.json"
    settings.write_text(
        json.dumps(
            {
                "launchModels": [
                    "llama3.2",
                    {"model": "qwen2.5-coder:14b", "name": "Qwen Coder", "provider": "ollama"},
                    {"model": "deepseek-r1", "baseURL": "http://localhost:11434/v1"},
                ]
            }
        )
    )

    models = ModelSettings(settings).load()

    assert [model.slug for model in models] == ["llama3-2", "qwen2-5-coder-14b", "deepseek-r1"]
    assert [model.provider for model in models] == ["generic-chat-completion-api"] * 3
    assert [model.base_url for model in models] == [
        "http://127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://localhost:11434/v1",
    ]


def test_catalog_preserves_context_and_visibility():
    model = ModelSettingsFixture.one()
    entry = catalog_entry(model)
    assert entry["slug"] == "claude-opus"
    assert entry["visibility"] == "list"
    assert entry["context_window"] == 200000
    assert "free" in entry["available_in_plans"]


def test_catalog_uses_per_model_compaction_limits(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model": "large-model",
                        "provider": "openai",
                        "base_url": "http://x/v1",
                        "api_key": "key",
                        "max_context_limit": 1000000,
                        "auto_compact_token_limit": 700000,
                        "truncation_limit": 120000,
                    }
                ]
            }
        )
    )
    [model] = ModelSettings(settings).load()
    entry = catalog_entry(model)
    assert entry["context_window"] == 1000000
    assert entry["auto_compact_token_limit"] == 700000
    assert entry["truncation_policy"] == {"mode": "tokens", "limit": 120000}


def test_api_key_env_and_systemd_credential_resolution(monkeypatch, tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "DIRECT_KEY").write_text("from-credential\n")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credential_dir))
    monkeypatch.setenv("ENV_KEY", "from-env")

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "env-model",
                        "model": "env-model",
                        "provider": "openai",
                        "base_url": "http://x/v1",
                        "api_key_env": "ENV_KEY",
                    },
                    {
                        "slug": "credential-model",
                        "model": "credential-model",
                        "provider": "openai",
                        "base_url": "http://x/v1",
                        "api_key_credential": "DIRECT_KEY",
                    },
                ]
            }
        )
    )

    env_model, credential_model = ModelSettings(settings).load()
    assert env_model.api_key == "from-env"
    assert credential_model.api_key == "from-credential"


def test_desktop_model_matrix_uses_credentials_and_provider_prefixes(tmp_path):
    payload = desktop_models_payload()
    rows = {row["slug"]: row for row in payload["models"]}

    assert "opencode-go-deepseek-v4-pro" in rows
    assert rows["opencode-go-deepseek-v4-pro"]["api_key_credential"] == "CLIPROXY_INTERNAL_API_KEY"
    assert rows["opencode-go-deepseek-v4-pro"]["provider_display_name"] == "CLIProxyAPI / OpenCode Go"
    assert rows["opencode-go-deepseek-v4-pro"]["base_url"] == "http://127.0.0.1:8317/v1"
    assert rows["opencode-go-deepseek-v4-pro"]["max_context_limit"] == 1000000
    assert rows["opencode-go-deepseek-v4-pro"]["no_image_support"] is True
    assert rows["opencode-go-kimi-k2-6"]["no_image_support"] is False
    assert rows["opencode-go-mimo-v2-5-pro"]["display_name"] == "MiMo v2.5 Pro"
    assert rows["opencode-go-mimo-v2-5-pro"]["provider_display_name"] == "CLIProxyAPI / OpenCode Go"
    assert rows["opencode-go-mimo-v2-5-pro"]["no_image_support"] is True
    assert rows["opencode-go-mimo-v2-5"]["no_image_support"] is False
    assert rows["commandcode-mimo-v2-5-pro"]["provider_display_name"] == "CLIProxyAPI / CommandCode"
    assert rows["commandcode-deepseek-v4-flash"]["provider"] == "generic-chat-completion-api"
    assert rows["commandcode-deepseek-v4-flash"]["base_url"] == "http://127.0.0.1:8317/v1"
    assert rows["commandcode-deepseek-v4-flash"]["provider_display_name"] == "CLIProxyAPI / CommandCode"
    assert rows["commandcode-deepseek-v4-flash"]["api_key_credential"] == "CLIPROXY_INTERNAL_API_KEY"
    assert rows["commandcode-deepseek-v4-flash"]["no_image_support"] is True
    assert rows["commandcode-deepseek-v4-flash"]["supports_tools"] is True
    assert "api_key" not in rows["commandcode-deepseek-v4-flash"]
    assert rows["grok-composer-2-5-fast"]["base_url"] == "http://127.0.0.1:8317/v1"
    assert rows["grok-4-3"]["provider_display_name"] == "CLIProxyAPI / xAI Grok OAuth"
    assert rows["grok-4-3"]["supports_reasoning"] is True
    assert "api_key" not in rows["grok-composer-2-5-fast"]

    output = write_desktop_models(tmp_path / "models.json")
    loaded = json.loads(output.read_text())
    assert loaded == payload
    assert "CLIPROXY_INTERNAL_API_KEY" in output.read_text()
    assert "DROID_BYOK_OPENCODE_GO_API_KEY" not in output.read_text()
    assert "sk-" not in output.read_text()


def test_desktop_model_matrix_can_use_live_cliproxyapi_discovery():
    payload = desktop_models_payload(
        cliproxyapi_models=[
            {"id": "deepseek/deepseek-v4-flash", "owned_by": "commandcode"},
            {
                "id": "example/custom-long",
                "owned_by": "example-provider",
                "contextWindow": 777000,
                "maxTokens": 65536,
                "autoCompactTokenLimit": 710000,
                "truncationLimit": 123456,
                "supportsTools": True,
                "supportsImageInputs": True,
                "supportsReasoning": True,
            },
            {"id": "grok-4.3", "owned_by": "xai"},
            {"id": "grok-imagine-image", "owned_by": "xai"},
            {"id": "commandcode/deepseek/deepseek-v4-pro", "owned_by": "cursor-commandcode"},
        ]
    )
    rows = {row["slug"]: row for row in payload["models"]}

    assert set(rows) == {"commandcode-deepseek-v4-flash", "example-provider-custom-long", "grok-4-3"}
    assert rows["commandcode-deepseek-v4-flash"]["model"] == "deepseek/deepseek-v4-flash"
    assert rows["commandcode-deepseek-v4-flash"]["provider_display_name"] == "CLIProxyAPI / CommandCode"
    assert rows["example-provider-custom-long"]["max_context_limit"] == 777000
    assert rows["example-provider-custom-long"]["max_output_tokens"] == 65536
    assert rows["example-provider-custom-long"]["auto_compact_token_limit"] == 710000
    assert rows["example-provider-custom-long"]["truncation_limit"] == 123456
    assert rows["example-provider-custom-long"]["supports_tools"] is True
    assert rows["example-provider-custom-long"]["no_image_support"] is False
    assert rows["example-provider-custom-long"]["supports_reasoning"] is True
    assert rows["grok-4-3"]["no_image_support"] is False


def test_live_cliproxyapi_discovery_reads_systemd_credential(monkeypatch, tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "CLIPROXY_INTERNAL_API_KEY").write_text("from-credential\n")
    monkeypatch.delenv("CLIPROXY_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credential_dir))

    captured: dict[str, str | None] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"data": [{"id": "zai-coding/glm-5.2", "owned_by": "cursor-zai-coding"}]}).encode()

    def fake_urlopen(req, *, timeout):
        captured["authorization"] = req.get_header("Authorization")
        captured["timeout"] = str(timeout)
        return Response()

    monkeypatch.setattr("codex_shim.desktop_models.request.urlopen", fake_urlopen)

    rows = discover_cliproxyapi_models(base_url="http://127.0.0.1:8317/v1", timeout=0.5)

    assert rows == [{"id": "zai-coding/glm-5.2", "owned_by": "cursor-zai-coding"}]
    assert captured == {"authorization": "Bearer from-credential", "timeout": "0.5"}


def test_desktop_model_matrix_uses_current_long_context_fallbacks():
    payload = desktop_models_payload(
        cliproxyapi_models=[
            {"id": "zai-coding/glm-5.2", "owned_by": "cursor-zai-coding"},
            {"id": "glm-5.2", "owned_by": "cursor-zai-coding"},
            {"id": "minimax-coding/MiniMax-M3", "owned_by": "cursor-minimax-coding"},
            {"id": "MiniMaxAI/MiniMax-M3", "owned_by": "commandcode"},
        ]
    )
    rows = {row["slug"]: row for row in payload["models"]}

    assert rows["cursor-zai-coding-glm-5-2"]["max_context_limit"] == 1000000
    assert rows["cursor-zai-coding-glm-5-2"]["max_output_tokens"] == 131072
    assert rows["cursor-zai-coding-glm-5-2"]["auto_compact_token_limit"] == 820000
    assert rows["cursor-zai-coding-glm-5-2-1"]["max_context_limit"] == 1000000
    assert rows["cursor-minimax-coding-minimax-m3"]["max_context_limit"] == 1000000
    assert rows["cursor-minimax-coding-minimax-m3"]["no_image_support"] is False
    assert rows["commandcode-minimax-m3"]["max_context_limit"] == 1000000
    assert rows["commandcode-minimax-m3"]["max_output_tokens"] == 131072


def test_desktop_model_matrix_allows_compaction_ratio_override(monkeypatch):
    monkeypatch.setenv("CODEX_SHIM_AUTO_COMPACT_RATIO", "0.9")
    monkeypatch.setenv("CODEX_SHIM_TRUNCATION_RATIO", "0.1")

    payload = desktop_models_payload(
        cliproxyapi_models=[
            {"id": "zai-coding/glm-5.2", "owned_by": "cursor-zai-coding"},
        ]
    )
    [row] = payload["models"]

    assert row["max_context_limit"] == 1000000
    assert row["auto_compact_token_limit"] == 900000
    assert row["truncation_limit"] == 100000


def test_desktop_model_matrix_keeps_xiaomi_mimo_token_plan_text_only():
    payload = desktop_models_payload(
        cliproxyapi_models=[
            {"id": "mimo-v2.5", "owned_by": "xiaomi-mimo"},
            {"id": "MiniMax-M3", "owned_by": "minimax-coding"},
        ]
    )
    rows = {row["slug"]: row for row in payload["models"]}

    mimo = rows["xiaomi-mimo-mimo-v2-5"]
    assert mimo["provider_display_name"] == "CLIProxyAPI / Xiaomi MiMo"
    assert mimo["base_url"] == "http://127.0.0.1:8317/v1"
    assert mimo["api_key_credential"] == "CLIPROXY_INTERNAL_API_KEY"
    assert mimo["no_image_support"] is True
    assert mimo["supports_tools"] is False
    assert mimo["supports_reasoning"] is False

    image_capable = rows["minimax-coding-minimax-m3"]
    assert image_capable["no_image_support"] is False


def test_catalog_display_names_are_route_first(tmp_path):
    payload = desktop_models_payload()
    settings = tmp_path / "models.json"
    settings.write_text(json.dumps(payload))
    models = ModelSettings(settings).load()
    rows = {model.slug: catalog_entry(model) for model in models}

    assert rows["opencode-go-mimo-v2-5-pro"]["display_name"] == "CLIProxyAPI / OpenCode Go / MiMo v2.5 Pro"
    assert rows["opencode-go-mimo-v2-5-pro"]["input_modalities"] == ["text"]
    assert rows["minimax-coding-minimax-m3"]["display_name"] == "CLIProxyAPI / MiniMax Coding / MiniMax M3"
    assert rows["minimax-coding-minimax-m3"]["input_modalities"] == ["text", "image"]
    assert rows["commandcode-deepseek-v4-flash"]["display_name"] == "CLIProxyAPI / CommandCode / DeepSeek V4 Flash"
    assert rows["grok-4-3"]["display_name"] == "CLIProxyAPI / xAI Grok OAuth / Grok 4.3"
    assert rows["grok-4-3"]["supports_reasoning_summaries"] is True


def test_write_catalog_keeps_configured_credential_rows_without_shell_secret(tmp_path, auth_missing):
    settings = tmp_path / "models.json"
    settings.write_text(json.dumps(desktop_models_payload()))
    models = ModelSettings(settings).load()
    catalog_path = tmp_path / "catalog.json"

    write_catalog(models, catalog_path)

    rows = {row["slug"]: row for row in json.loads(catalog_path.read_text())["models"]}
    assert rows["opencode-go-mimo-v2-5-pro"]["display_name"] == "CLIProxyAPI / OpenCode Go / MiMo v2.5 Pro"
    assert rows["opencode-go-mimo-v2-5-pro"]["input_modalities"] == ["text"]
    assert rows["minimax-coding-minimax-m3"]["input_modalities"] == ["text", "image"]


def test_commandcode_settings_row_loads_as_cliproxyapi_route(monkeypatch, tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "CLIPROXY_INTERNAL_API_KEY").write_text("cpa-secret\n")

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "commandcode-deepseek-v4-flash",
                        "model": "deepseek/deepseek-v4-flash",
                        "display_name": "DeepSeek V4 Flash",
                        "provider": "generic-chat-completion-api",
                        "base_url": "http://127.0.0.1:8317/v1",
                        "api_key_credential": "CLIPROXY_INTERNAL_API_KEY",
                    }
                ]
            }
        )
    )

    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credential_dir))
    [model] = ModelSettings(settings).load()

    assert model.is_openai_chat is True
    assert model.api_key == "cpa-secret"


def test_stale_commandcode_settings_row_is_normalized_to_cliproxyapi(monkeypatch, tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "CLIPROXY_INTERNAL_API_KEY").write_text("cpa-secret\n")

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "commandcode-deepseek-v4-pro",
                        "model": "deepseek/deepseek-v4-pro",
                        "display_name": "DeepSeek V4 Pro",
                        "provider": "commandcode",
                        "base_url": "https://api.commandcode.ai",
                        "api_key_credential": "COMMANDCODE_API_KEY",
                    }
                ]
            }
        )
    )

    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credential_dir))
    [model] = ModelSettings(settings).load()

    assert model.provider == "generic-chat-completion-api"
    assert model.base_url == "http://127.0.0.1:8317/v1"
    assert model.raw["api_key_credential"] == "CLIPROXY_INTERNAL_API_KEY"
    assert model.api_key == "cpa-secret"


def test_default_missing_settings_allows_chatgpt_only(monkeypatch, tmp_path):
    missing = tmp_path / "missing-default.json"
    monkeypatch.setattr("codex_shim.settings.DEFAULT_SETTINGS", missing)
    assert ModelSettings().load() == []


def test_cli_load_models_missing_custom_settings_has_actionable_error(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(SystemExit) as exc:
        cli._load_models(missing)
    assert "Settings file not found" in str(exc.value)
    assert "--settings /path/to/models.json" in str(exc.value)


def test_cli_resolves_chatgpt_passthrough_slug_when_auth_present(auth_present):
    assert cli._resolve_model_slug([], "gpt-5.5") == "gpt-5.5"
    assert cli._resolve_model_slug([], "openai-gpt-5-5") == "gpt-5.5"


def test_cli_rejects_chatgpt_passthrough_slug_when_auth_missing(auth_missing):
    with pytest.raises(SystemExit) as exc:
        cli._resolve_model_slug([], "gpt-5.5")
    assert "codex login" in str(exc.value)


def test_list_models_includes_chatgpt_passthrough_when_auth_present(monkeypatch, capsys, auth_present):
    monkeypatch.setattr(cli, "_load_models", lambda _settings_path: [])
    assert cli.list_models("unused") == 0
    assert "gpt-5.5" in capsys.readouterr().out


def test_list_models_hides_chatgpt_passthrough_when_auth_missing(monkeypatch, capsys, auth_missing):
    monkeypatch.setattr(cli, "_load_models", lambda _settings_path: [])
    assert cli.list_models("unused") == 1
    out = capsys.readouterr()
    assert "gpt-5.5" not in out.out
    assert "codex login" in out.err


def test_cli_load_models_invalid_json_has_actionable_error(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{")
    with pytest.raises(SystemExit) as exc:
        cli._load_models(settings)
    assert "Settings file is not valid JSON" in str(exc.value)


def test_chatgpt_passthrough_available_requires_explicit_enable_and_access_token(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    assert chatgpt_passthrough_available(missing) is False
    no_tokens = tmp_path / "no-tokens.json"
    no_tokens.write_text(json.dumps({}))
    assert chatgpt_passthrough_available(no_tokens) is False
    empty_token = tmp_path / "empty.json"
    empty_token.write_text(json.dumps({"tokens": {"access_token": ""}}))
    assert chatgpt_passthrough_available(empty_token) is False
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"tokens": {"access_token": "x"}}))
    assert chatgpt_passthrough_available(valid) is False
    monkeypatch.setenv("CODEX_SHIM_ENABLE_CHATGPT", "1")
    assert chatgpt_passthrough_available(valid) is True


def test_write_catalog_omits_gpt55_when_auth_missing(tmp_path, auth_missing):
    catalog_path = tmp_path / "catalog.json"
    write_catalog([], catalog_path)
    data = json.loads(catalog_path.read_text())
    assert data == {"models": []}


def test_write_catalog_includes_gpt_models_when_auth_present(tmp_path, auth_present, monkeypatch):
    missing_cache = tmp_path / "missing-models-cache.json"
    monkeypatch.setattr("codex_shim.settings.DEFAULT_CODEX_MODELS_CACHE", missing_cache)
    catalog_path = tmp_path / "catalog.json"
    write_catalog([], catalog_path)
    data = json.loads(catalog_path.read_text())
    assert [model["slug"] for model in data["models"]] == list(FALLBACK_CHATGPT_PASSTHROUGH_SLUGS)


def test_managed_config_uses_linux_catalog_path(monkeypatch):
    monkeypatch.setattr(cli, "CATALOG_PATH", Path("/tmp/codex-shim/custom_model_catalog.json"))
    top_block, _ = cli._managed_config_blocks("vendor\\model", 8765)
    assert 'model = "vendor\\\\model"' in top_block
    assert 'model_catalog_json = "/tmp/codex-shim/custom_model_catalog.json"' in top_block


def test_install_codex_config_is_idempotent(monkeypatch, tmp_path):
    settings = tmp_path / "models.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {"model": "llama3.2", "display_name": "Llama", "provider": "generic-chat-completion-api", "base_url": "http://127.0.0.1:11434/v1"}
                ]
            }
        )
    )
    config_path = tmp_path / ".codex" / "config.toml"
    monkeypatch.setattr(cli, "RUNTIME_DIR", tmp_path / ".codex-shim")
    monkeypatch.setattr(cli, "CODEX_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli, "CODEX_CONFIG_BACKUP_PATH", tmp_path / ".codex-shim" / "config.toml.before-codex-shim")

    cli.install_codex_config(settings, 8765, "llama3.2")
    cli.install_codex_config(settings, 8765, "llama3.2")

    text = config_path.read_text()
    assert text.count("[model_providers.codex_shim]") == 1
    assert text.count("model_provider = \"codex_shim\"") == 1
    assert text.count("model_catalog_json") == 1


def test_install_and_restore_preserve_displaced_top_level_config(monkeypatch, tmp_path):
    settings = tmp_path / "models.json"
    settings.write_text(
        json.dumps(
            {
                "models": [
                    {"model": "llama3.2", "display_name": "Llama", "provider": "generic-chat-completion-api", "base_url": "http://127.0.0.1:11434/v1"}
                ]
            }
        )
    )
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        'model = "gpt-5.5"\n'
        'model_provider = "openai"\n'
        'model_catalog_json = "/tmp/catalog.json"\n'
        '\n[profiles.dev]\nmodel = "profile-model"\n'
    )
    monkeypatch.setattr(cli, "RUNTIME_DIR", tmp_path / ".codex-shim")
    monkeypatch.setattr(cli, "CODEX_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli, "CODEX_CONFIG_BACKUP_PATH", tmp_path / ".codex-shim" / "config.toml.before-codex-shim")

    cli.install_codex_config(settings, 8765, "llama3.2")
    installed = config_path.read_text()
    assert cli.PREVIOUS_TOP_LEVEL_PREFIX in installed
    assert '\nmodel = "llama3-2"\n' in installed
    assert '\nmodel_provider = "openai"\n' not in installed
    assert '[profiles.dev]\nmodel = "profile-model"' in installed

    cli.restore_codex_config()
    restored = config_path.read_text().rstrip() + "\n"
    assert restored == (
        'model = "gpt-5.5"\n'
        'model_provider = "openai"\n'
        'model_catalog_json = "/tmp/catalog.json"\n'
        '[profiles.dev]\nmodel = "profile-model"\n'
    )


def test_current_managed_model_ignores_user_top_level_and_stale_managed(monkeypatch, tmp_path, auth_missing):
    config_path = tmp_path / ".codex" / "codex-shim.config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        'model = "user-top"\n'
        f'{cli.MANAGED_BEGIN}\n'
        'model = "stale-managed"\n'
        f'{cli.MANAGED_END}\n'
    )
    monkeypatch.setattr(cli, "CODEX_SHIM_PROFILE_PATH", config_path)

    model = ModelSettingsFixture.one()
    assert cli._current_managed_model() == "stale-managed"
    assert cli._resolve_model_slug([model], None) == "claude-opus"


def test_loopback_no_proxy_adds_upper_and_lowercase_entries():
    env = cli._with_loopback_no_proxy({"NO_PROXY": "example.com,localhost"})

    assert env["NO_PROXY"] == "example.com,localhost,127.0.0.1,::1"
    assert env["no_proxy"] == "127.0.0.1,localhost,::1"


def test_profile_cli_wrapper_uses_config_overrides_for_app_server(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "CODEX_SHIM_PROFILE_CLI_PATH", tmp_path / "bin" / "codex-shim-profile-codex")
    monkeypatch.setattr(cli, "CODEX_SHIM_DESKTOP_WRAPPER_PATH", tmp_path / "bin" / "codex-desktop-shim")
    monkeypatch.setattr(cli, "CATALOG_PATH", Path("/tmp/custom_model_catalog.json"))

    cli._write_profile_wrappers("opencode-go-mimo-v2-5-pro", "CLIProxyAPI / OpenCode Go / MiMo v2.5 Pro", 8765)

    text = cli.CODEX_SHIM_PROFILE_CLI_PATH.read_text()
    assert "--profile" not in text
    assert 'model="opencode-go-mimo-v2-5-pro"' in text
    assert 'model_provider="codex_shim"' in text
    assert 'model_catalog_json="/tmp/custom_model_catalog.json"' in text
    assert 'model_providers.codex_shim.name="CLIProxyAPI / OpenCode Go / MiMo v2.5 Pro"' in text
    assert '"$@"' in text

    desktop_text = cli.CODEX_SHIM_DESKTOP_WRAPPER_PATH.read_text()
    assert "/home/" not in desktop_text
    assert "CODEX_SHIM_DESKTOP_APP_DIR" in desktop_text
    assert "/opt/codex-desktop" in desktop_text


def test_patch_app_is_linux_only(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "darwin")

    assert cli.patch_codex_app() == 1
    assert "Linux Codex Desktop overlays only" in capsys.readouterr().err


def test_restore_app_is_linux_only(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "darwin")

    assert cli.restore_codex_app_bundle() == 1
    assert "Linux Codex Desktop overlays only" in capsys.readouterr().err


def test_linux_desktop_command_prefers_explicit_launcher(monkeypatch):
    monkeypatch.setenv("CODEX_DESKTOP_LINUX_LAUNCHER", "/custom/codex-desktop")

    assert cli._linux_codex_desktop_command("/work") == ["/custom/codex-desktop", "/work"]


def test_desktop_bundle_patch_applies_model_picker_and_sidebar(tmp_path):
    assets = tmp_path / "webview" / "assets"
    assets.mkdir(parents=True)
    model_bundle = assets / "models-and-reasoning-efforts-test.js"
    sidebar_bundle = assets / "app-server-manager-signals-test.js"
    model_bundle.write_text("before let a=[],o=null,s=i&&e!==`amazonBedrock`; after")
    sidebar_bundle.write_text(
        "before listRecentThreads({cursor:e,limit:t}){return this.params.requestClient.sendRequest(`thread/list`,"
        "{limit:t,cursor:e,sortKey:this.recentConversationSortKey,modelProviders:null,archived:!1,sourceKinds:he})} after"
    )

    assert cli._patch_codex_desktop_bundles(tmp_path) is True
    assert "let a=[],o=null,s=!1;" in model_bundle.read_text()
    assert "modelProviders:[]" in sidebar_bundle.read_text()
    assert cli._patch_codex_desktop_bundles(tmp_path) is False


def test_desktop_bundle_patch_fails_when_sidebar_needle_is_missing(tmp_path):
    assets = tmp_path / "webview" / "assets"
    assets.mkdir(parents=True)
    (assets / "models-and-reasoning-efforts-test.js").write_text("let a=[],o=null,s=i&&e!==`amazonBedrock`;")
    (assets / "app-server-manager-signals-test.js").write_text("different build")

    assert cli._patch_codex_desktop_bundles(tmp_path) is None


class ModelSettingsFixture:
    @staticmethod
    def one():
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "model": "claude-opus",
                            "display_name": "Claude Opus",
                            "provider": "anthropic",
                            "base_url": "http://anthropic",
                            "apiKey": "stub",
                            "max_context_limit": 200000,
                        }
                    ]
                }
            )
        )
        return ModelSettings(path).load()[0]
