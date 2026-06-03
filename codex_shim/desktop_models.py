from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def desktop_models_payload(*, include_commandcode: bool = True, include_cpa_oauth: bool = True) -> dict[str, Any]:
    """Return the bundled Linux desktop provider-prefixed model matrix.

    The generated settings intentionally contain credential names, not secret
    values. The codex-shim systemd unit should load matching encrypted
    credentials via LoadCredentialEncrypted=.
    """

    rows: list[dict[str, Any]] = []
    rows.extend(_zai_coding_models())
    rows.extend(_minimax_coding_models())
    rows.extend(_opencode_go_models())
    rows.extend(_opencode_zen_models())
    rows.extend(_xiaomi_token_plan_models())
    rows.extend(_crofai_models())
    if include_commandcode:
        rows.extend(_commandcode_models())
    if include_cpa_oauth:
        rows.extend(_cliproxy_oauth_models())
    return {"models": rows}


def write_desktop_models(
    path: Path,
    *,
    include_commandcode: bool = True,
    include_cpa_oauth: bool = True,
) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = desktop_models_payload(
        include_commandcode=include_commandcode,
        include_cpa_oauth=include_cpa_oauth,
    )
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def _row(
    *,
    slug: str,
    model: str,
    display_name: str,
    provider: str,
    base_url: str,
    provider_display_name: str,
    credential: str | None,
    context: int,
    output: int,
    image: bool,
    index: int,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slug": slug,
        "model": model,
        "display_name": display_name,
        "provider": provider,
        "provider_display_name": provider_display_name,
        "base_url": base_url,
        "max_context_limit": context,
        "max_output_tokens": output,
        "auto_compact_token_limit": max(8_000, int(context * 0.82)),
        "truncation_limit": min(128_000, max(16_000, int(context * 0.22))),
        "no_image_support": not image,
        "index": index,
        "generated_by": "codex-shim-desktop-matrix",
    }
    if credential:
        row["api_key_credential"] = credential
    else:
        row["api_key"] = "dummy"
    if extra_headers:
        row["extra_headers"] = dict(extra_headers)
    return row


def _zai_coding_models() -> list[dict[str, Any]]:
    base = "https://api.z.ai/api/coding/paas/v4"
    credential = "DROID_BYOK_ZAI_CODING_API_KEY"
    provider = "Z.ai Coding"
    return [
        _row(
            slug="zai-glm-5-1",
            model="glm-5.1",
            display_name="GLM 5.1",
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name=provider,
            credential=credential,
            context=200_000,
            output=131_072,
            image=False,
            index=10,
        ),
        _row(
            slug="zai-glm-5",
            model="glm-5",
            display_name="GLM 5",
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name=provider,
            credential=credential,
            context=202_752,
            output=131_072,
            image=False,
            index=11,
        ),
        _row(
            slug="zai-glm-4-7",
            model="glm-4.7",
            display_name="GLM 4.7",
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name=provider,
            credential=credential,
            context=204_800,
            output=131_072,
            image=False,
            index=12,
        ),
    ]


def _minimax_coding_models() -> list[dict[str, Any]]:
    credential = "DROID_BYOK_MINIMAX_API_KEY"
    return [
        _row(
            slug="minimax-m3",
            model="MiniMax-M3",
            display_name="MiniMax M3",
            provider="generic-chat-completion-api",
            base_url="https://api.minimax.io/v1",
            provider_display_name="MiniMax Coding",
            credential=credential,
            context=512_000,
            output=131_072,
            image=True,
            index=20,
        ),
        _row(
            slug="minimax-m2-7",
            model="MiniMax-M2.7",
            display_name="MiniMax M2.7",
            provider="generic-chat-completion-api",
            base_url="https://api.minimax.io/v1",
            provider_display_name="MiniMax Coding",
            credential=credential,
            context=204_800,
            output=131_072,
            image=False,
            index=21,
        ),
        _row(
            slug="minimax-m2-7-highspeed",
            model="MiniMax-M2.7-highspeed",
            display_name="MiniMax M2.7 Highspeed",
            provider="generic-chat-completion-api",
            base_url="https://api.minimax.io/v1",
            provider_display_name="MiniMax Coding",
            credential=credential,
            context=204_800,
            output=131_072,
            image=False,
            index=22,
        ),
    ]


def _opencode_go_models() -> list[dict[str, Any]]:
    base = "https://opencode.ai/zen/go/v1"
    credential = "DROID_BYOK_OPENCODE_GO_API_KEY"
    specs = [
        ("opencode-go-deepseek-v4-pro", "deepseek-v4-pro", "DeepSeek V4 Pro", "generic-chat-completion-api", 1_000_000, 384_000, False),
        ("opencode-go-deepseek-v4-flash", "deepseek-v4-flash", "DeepSeek V4 Flash", "generic-chat-completion-api", 1_000_000, 384_000, False),
        ("opencode-go-kimi-k2-6", "kimi-k2.6", "Kimi K2.6", "generic-chat-completion-api", 262_144, 65_536, True),
        ("opencode-go-kimi-k2-5", "kimi-k2.5", "Kimi K2.5", "generic-chat-completion-api", 262_144, 65_536, True),
        ("opencode-go-glm-5-1", "glm-5.1", "GLM 5.1", "generic-chat-completion-api", 202_752, 32_768, False),
        ("opencode-go-glm-5", "glm-5", "GLM 5", "generic-chat-completion-api", 202_752, 32_768, False),
        ("opencode-go-mimo-v2-5-pro", "mimo-v2.5-pro", "MiMo v2.5 Pro", "generic-chat-completion-api", 1_048_576, 128_000, False),
        ("opencode-go-mimo-v2-5", "mimo-v2.5", "MiMo v2.5", "generic-chat-completion-api", 1_000_000, 128_000, True),
        ("opencode-go-minimax-m3", "minimax-m3", "MiniMax M3", "anthropic", 512_000, 131_072, True),
        ("opencode-go-minimax-m2-7", "minimax-m2.7", "MiniMax M2.7", "anthropic", 204_800, 131_072, False),
        ("opencode-go-minimax-m2-5", "minimax-m2.5", "MiniMax M2.5", "anthropic", 204_800, 65_536, False),
        ("opencode-go-qwen3-7-max", "qwen3.7-max", "Qwen3.7 Max", "anthropic", 1_000_000, 65_536, False),
        ("opencode-go-qwen3-6-plus", "qwen3.6-plus", "Qwen3.6 Plus", "anthropic", 262_144, 65_536, False),
    ]
    return [
        _row(
            slug=slug,
            model=model,
            display_name=display_name,
            provider=provider,
            base_url=base,
            provider_display_name="OpenCode Go",
            credential=credential,
            context=context,
            output=output,
            image=image,
            index=100 + i,
        )
        for i, (slug, model, display_name, provider, context, output, image) in enumerate(specs)
    ]


def _opencode_zen_models() -> list[dict[str, Any]]:
    base = "https://opencode.ai/zen/v1"
    credential = "DROID_BYOK_OPENCODE_GO_API_KEY"
    specs = [
        ("opencode-zen-big-pickle", "big-pickle", "Big Pickle", "generic-chat-completion-api", 200_000, 32_000, False),
        ("opencode-zen-deepseek-v4-flash-free", "deepseek-v4-flash-free", "DeepSeek V4 Flash Free", "generic-chat-completion-api", 200_000, 128_000, False),
        ("opencode-zen-minimax-m3-free", "minimax-m3-free", "MiniMax M3 Free", "anthropic", 200_000, 32_000, True),
        ("opencode-zen-mimo-v2-5-free", "mimo-v2.5-free", "MiMo v2.5 Free", "generic-chat-completion-api", 200_000, 32_000, True),
        ("opencode-zen-nemotron-3-super-free", "nemotron-3-super-free", "Nemotron 3 Super Free", "generic-chat-completion-api", 204_800, 128_000, False),
    ]
    return [
        _row(
            slug=slug,
            model=model,
            display_name=display_name,
            provider=provider,
            base_url=base,
            provider_display_name="OpenCode Zen",
            credential=credential,
            context=context,
            output=output,
            image=image,
            index=200 + i,
        )
        for i, (slug, model, display_name, provider, context, output, image) in enumerate(specs)
    ]


def _xiaomi_token_plan_models() -> list[dict[str, Any]]:
    base = "https://token-plan-sgp.xiaomimimo.com/v1"
    credential = "XIAOMI_MIMO_TOKEN_PLAN_API_KEY"
    return [
        _row(
            slug="xiaomi-mimo-v2-5-pro",
            model="mimo-v2.5-pro",
            display_name="Xiaomi MiMo v2.5 Pro",
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name="Xiaomi Token Plan",
            credential=credential,
            context=1_048_576,
            output=131_072,
            image=False,
            index=300,
        ),
        _row(
            slug="xiaomi-mimo-v2-5",
            model="mimo-v2.5",
            display_name="Xiaomi MiMo v2.5",
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name="Xiaomi Token Plan",
            credential=credential,
            context=1_048_576,
            output=131_072,
            image=False,
            index=301,
        ),
    ]


def _crofai_models() -> list[dict[str, Any]]:
    base = "https://crof.ai/v1"
    credential = "CROFAI_API_KEY"
    specs = [
        ("crof-kimi-k2-6-precision", "kimi-k2.6-precision", "Kimi K2.6 Precision", 262_144, 262_144, True),
        ("crof-deepseek-v4-pro", "deepseek-v4-pro", "DeepSeek V4 Pro", 1_000_000, 131_072, False),
        ("crof-glm-5-1", "glm-5.1", "GLM 5.1", 202_752, 202_752, False),
    ]
    return [
        _row(
            slug=slug,
            model=model,
            display_name=display_name,
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name="CrofAI",
            credential=credential,
            context=context,
            output=output,
            image=image,
            index=400 + i,
        )
        for i, (slug, model, display_name, context, output, image) in enumerate(specs)
    ]


def _commandcode_models() -> list[dict[str, Any]]:
    base = "http://127.0.0.1:8318/v1"
    specs = [
        ("commandcode-deepseek-v4-pro", "deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "CommandCode/DeepSeek"),
        ("commandcode-deepseek-v4-flash", "deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "CommandCode/DeepSeek"),
        ("commandcode-glm-5-1", "zai-org/GLM-5.1", "GLM 5.1", "CommandCode/Z.ai"),
        ("commandcode-kimi-k2-6", "moonshotai/Kimi-K2.6", "Kimi K2.6", "CommandCode/Moonshot"),
        ("commandcode-minimax-m3", "MiniMaxAI/MiniMax-M3", "MiniMax M3", "CommandCode/MiniMax"),
        ("commandcode-mimo-v2-5-pro", "xiaomi/mimo-v2.5-pro", "Xiaomi MiMo v2.5 Pro", "CommandCode/Xiaomi"),
        ("commandcode-qwen3-7-max", "Qwen/Qwen3.7-Max", "Qwen3.7 Max", "CommandCode/Qwen"),
        ("commandcode-step-3-5-flash", "stepfun/Step-3.5-Flash", "Step 3.5 Flash", "CommandCode/StepFun"),
    ]
    return [
        _row(
            slug=slug,
            model=model,
            display_name=display_name,
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name=provider_name,
            credential=None,
            context=128_000,
            output=32_768,
            image=False,
            index=500 + i,
        )
        for i, (slug, model, display_name, provider_name) in enumerate(specs)
    ]


def _cliproxy_oauth_models() -> list[dict[str, Any]]:
    base = "http://127.0.0.1:8317/v1"
    credential = "CLIPROXY_INTERNAL_API_KEY"
    specs = [
        ("grok-composer-2-5-fast", "grok-composer-2.5-fast", "Grok Composer 2.5 Fast", 200_000, 30_000, False),
        ("grok-4-3", "grok-4.3", "Grok 4.3", 1_000_000, 30_000, True),
        ("grok-4-20-reasoning", "grok-4.20-0309-reasoning", "Grok 4.20 Reasoning", 2_000_000, 30_000, True),
    ]
    return [
        _row(
            slug=slug,
            model=model,
            display_name=display_name,
            provider="generic-chat-completion-api",
            base_url=base,
            provider_display_name="CLIProxyAPI/xAI Grok CLI",
            credential=credential,
            context=context,
            output=output,
            image=image,
            index=600 + i,
        )
        for i, (slug, model, display_name, context, output, image) in enumerate(specs)
    ]