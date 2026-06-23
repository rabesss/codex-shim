from __future__ import annotations

from .settings import (
    CHATGPT_MODEL_SLUG,
    CLIPROXYAPI_BASE_URL,
    PROVIDER_NAME,
    ShimModel,
    load_chatgpt_passthrough_catalog_models,
)


PLAN_TIERS = ["free", "plus", "pro", "team", "business", "enterprise"]
UPSTREAM_PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "minimaxai": "MiniMax",
    "moonshotai": "Moonshot",
    "qwen": "Qwen",
    "stepfun": "StepFun",
    "xiaomi": "Xiaomi",
    "zai-org": "Z.ai",
}


def catalog_entry(model: ShimModel) -> dict:
    context = model.max_context_limit or _default_context(model)
    compact = model.auto_compact_token_limit or max(8_000, int(context * 0.8))
    truncation = model.truncation_limit or min(64_000, max(8_000, int(context * 0.32)))
    reasoning = _reasoning_effort(model)
    supports_reasoning = _raw_bool(model, "supports_reasoning", default=True)
    supports_tools = _raw_bool(model, "supports_tools", default=False)
    provider_label = _provider_label(model)
    supports_streaming = _raw_bool(model, "supports_streaming", default=True)
    return {
        "slug": model.slug,
        "model": model.model,
        "model_provider": PROVIDER_NAME,
        "provider": model.provider,
        "display_name": model.display_name,
        "provider_display_name": provider_label,
        "description": f"{model.display_name} via {provider_label or 'local Codex shim'}.",
        "context_window": context,
        "max_context_window": context,
        "auto_compact_token_limit": compact,
        "truncation_policy": {"mode": "tokens", "limit": truncation},
        "default_reasoning_level": reasoning,
        "supported_reasoning_levels": [
            {"effort": "low", "description": "Faster, lighter reasoning"},
            {"effort": "medium", "description": "Balanced speed and reasoning"},
            {"effort": "high", "description": "Deeper reasoning"},
            {"effort": "xhigh", "description": "Maximum reasoning where supported"},
        ],
        "default_reasoning_summary": "auto" if supports_reasoning else "none",
        "reasoning_summary_format": "experimental",
        "supports_reasoning_summaries": supports_reasoning,
        "default_verbosity": "low",
        "support_verbosity": False,
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text_and_image",
        "supports_search_tool": False,
        "supports_parallel_tool_calls": supports_tools,
        "supports_tools": supports_tools,
        "supports_reasoning": supports_reasoning,
        "supports_streaming": supports_streaming,
        "experimental_supported_tools": [],
        "input_modalities": ["text"] if model.no_image_support else ["text", "image"],
        "supports_image_detail_original": not model.no_image_support,
        "shell_type": "shell_command",
        "visibility": "list",
        "minimal_client_version": "0.0.1",
        "supported_in_api": True,
        "availability_nux": None,
        "upgrade": None,
        "priority": max(1, 1000 - model.index),
        "prefer_websockets": False,
        "available_in_plans": PLAN_TIERS,
        "base_instructions": "You are a coding agent running in Codex through a local custom-model shim.",
        "source": "CLIProxyAPI" if model.base_url == CLIPROXYAPI_BASE_URL else "codex-shim",
        "upstream_model_id": model.model,
        "model_messages": {
            "instructions_template": (
                "You are Codex running on {model_name} through a local all-model shim. "
                "Be a helpful, direct coding collaborator."
            ),
            "instructions_variables": {"model_name": model.display_name},
        },
    }


def chatgpt_passthrough_entries() -> list[dict]:
    """Catalog entries for GPT models routed through ChatGPT passthrough."""
    entries: list[dict] = []
    for raw in load_chatgpt_passthrough_catalog_models():
        entry = dict(raw)
        display_name = str(entry.get("display_name") or entry.get("slug") or "ChatGPT")
        entry["display_name"] = with_provider_prefix(display_name, "ChatGPT/OpenAI")
        entry["visibility"] = "list"
        entry.setdefault("available_in_plans", PLAN_TIERS)
        entry.setdefault("minimal_client_version", "0.0.1")
        entry.setdefault("supported_in_api", True)
        if entry.get("slug") == CHATGPT_MODEL_SLUG:
            entry["isDefault"] = True
            entry["priority"] = max(int(entry.get("priority") or 0), 10000)
        entries.append(entry)
    return entries


def chatgpt_passthrough_entry() -> dict:
    """Catalog entry for the default GPT-5.5 ChatGPT passthrough model."""
    for entry in chatgpt_passthrough_entries():
        if entry.get("slug") == CHATGPT_MODEL_SLUG:
            return entry
    return chatgpt_passthrough_entries()[0]


def shim_route_catalog_entry(
    entry: dict,
    *,
    provider: str,
    provider_display_name: str,
    source: str,
) -> dict:
    normalized = dict(entry)
    slug = str(normalized.get("slug") or "").strip()
    model = str(normalized.get("model") or normalized.get("upstream_model_id") or slug).strip() or slug
    normalized["model"] = model
    normalized["model_provider"] = PROVIDER_NAME
    normalized["provider"] = provider
    normalized["provider_display_name"] = provider_display_name
    normalized["source"] = source
    normalized["supports_tools"] = bool(
        normalized.get("supports_tools", normalized.get("supports_parallel_tool_calls", False))
    )
    normalized["supports_reasoning"] = bool(
        normalized.get("supports_reasoning", normalized.get("supports_reasoning_summaries", False))
    )
    normalized["supports_streaming"] = bool(normalized.get("supports_streaming", True))
    normalized["upstream_model_id"] = model
    return normalized


def with_provider_prefix(display_name: str, provider_label: str) -> str:
    if not provider_label:
        return display_name
    prefix = f"{provider_label} / "
    if display_name.startswith(prefix):
        return display_name
    return f"{provider_label} / {display_name}"


def _default_context(model: ShimModel) -> int:
    lower = f"{model.model} {model.display_name}".lower()
    if "claude" in lower:
        return 200_000
    if "gpt-5" in lower:
        return 400_000
    if "gemini" in lower:
        return 1_000_000
    return 128_000


def _reasoning_effort(model: ShimModel) -> str:
    if not _raw_bool(model, "supports_reasoning", default=True):
        return "low"
    lower = model.display_name.lower()
    if "xhigh" in lower or "x-high" in lower:
        return "xhigh"
    if "high" in lower:
        return "high"
    if "medium" in lower:
        return "medium"
    if "low" in lower:
        return "low"
    return "medium"


def _raw_bool(model: ShimModel, key: str, *, default: bool) -> bool:
    value = model.raw.get(key)
    if value is None:
        camel = key.split("_")[0] + "".join(part[:1].upper() + part[1:] for part in key.split("_")[1:])
        value = model.raw.get(camel)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _provider_label(model: ShimModel) -> str:
    configured = str(
        model.raw.get("provider_display_name")
        or model.raw.get("providerDisplayName")
        or model.raw.get("provider_label")
        or model.raw.get("providerLabel")
        or ""
    ).strip()
    if configured:
        cli_prefix = "CLIProxyAPI / "
        cursor_prefix = "Cursor "
        if configured.startswith(cli_prefix + cursor_prefix):
            return cli_prefix + configured.removeprefix(cli_prefix + cursor_prefix)
        if configured.startswith(cursor_prefix):
            return configured.removeprefix(cursor_prefix)
        return configured

    upstream = _upstream_provider_label(model.model)
    if model.base_url == CLIPROXYAPI_BASE_URL:
        return f"CLIProxyAPI/{upstream}" if upstream else "CLIProxyAPI"
    if upstream:
        return upstream
    if model.provider == "generic-chat-completion-api":
        return "OpenAI-compatible"
    return model.provider


def _upstream_provider_label(model_name: str) -> str:
    owner = model_name.split("/", 1)[0].strip().lower()
    return UPSTREAM_PROVIDER_LABELS.get(owner, owner)
