from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib import error, request


CLIPROXYAPI_BASE_URL = "http://127.0.0.1:8317/v1"
CLIPROXYAPI_CREDENTIAL = "CLIPROXY_INTERNAL_API_KEY"
DISCOVERY_TIMEOUT_SECONDS = 2.0

OWNER_LABELS = {
    "zai-coding": "Z.ai Coding",
    "minimax-coding": "MiniMax Coding",
    "opencode-go": "OpenCode Go",
    "opencode-zen": "OpenCode Zen",
    "xiaomi-mimo": "Xiaomi MiMo",
    "crofai": "CrofAI",
    "commandcode": "CommandCode",
    "xai": "xAI Grok OAuth",
}

SKIPPED_DISCOVERY_OWNERS = {
    # Cursor relay routes are intentionally scoped to Cursor. Codex gets the
    # underlying CLIProxyAPI provider routes instead.
    "cursor-commandcode",
    "cursor-crofai",
    "cursor-opencode-zen",
    "cursor-xiaomi-mimo",
}
NON_CHAT_MODEL_MARKERS = ("imagine", "image-quality", "video")
TOOL_CAPABLE_OWNERS = {
    "zai-coding",
    "minimax-coding",
    "opencode-go",
    "opencode-zen",
    "crofai",
    "commandcode",
}

BOOTSTRAP_MODELS: tuple[tuple[str, str], ...] = (
    ("zai-coding", "glm-5.1"),
    ("zai-coding", "glm-5"),
    ("zai-coding", "glm-4.7"),
    ("minimax-coding", "MiniMax-M3"),
    ("minimax-coding", "MiniMax-M2.7"),
    ("minimax-coding", "MiniMax-M2.7-highspeed"),
    ("opencode-go", "deepseek-v4-pro"),
    ("opencode-go", "deepseek-v4-flash"),
    ("opencode-go", "kimi-k2.6"),
    ("opencode-go", "kimi-k2.5"),
    ("opencode-go", "glm-5.1"),
    ("opencode-go", "glm-5"),
    ("opencode-go", "mimo-v2.5-pro"),
    ("opencode-go", "mimo-v2.5"),
    ("opencode-go", "minimax-m2.7"),
    ("opencode-go", "minimax-m2.5"),
    ("opencode-go", "qwen3.7-max"),
    ("opencode-go", "qwen3.6-plus"),
    ("opencode-go", "qwen3.5-plus"),
    ("opencode-zen", "big-pickle"),
    ("opencode-zen", "deepseek-v4-flash-free"),
    ("opencode-zen", "mimo-v2.5-free"),
    ("opencode-zen", "minimax-m3-free"),
    ("opencode-zen", "nemotron-3-super-free"),
    ("crofai", "kimi-k2.6-precision"),
    ("commandcode", "deepseek/deepseek-v4-pro"),
    ("commandcode", "deepseek/deepseek-v4-flash"),
    ("commandcode", "zai-org/GLM-5.1"),
    ("commandcode", "zai-org/GLM-5"),
    ("commandcode", "moonshotai/Kimi-K2.6"),
    ("commandcode", "moonshotai/Kimi-K2.5"),
    ("commandcode", "MiniMaxAI/MiniMax-M3"),
    ("commandcode", "MiniMaxAI/MiniMax-M2.7"),
    ("commandcode", "MiniMaxAI/MiniMax-M2.5"),
    ("commandcode", "xiaomi/mimo-v2.5-pro"),
    ("commandcode", "xiaomi/mimo-v2.5"),
    ("commandcode", "Qwen/Qwen3.7-Max"),
    ("commandcode", "Qwen/Qwen3.6-Max-Preview"),
    ("commandcode", "Qwen/Qwen3.6-Plus"),
    ("commandcode", "stepfun/Step-3.5-Flash"),
    ("xai", "grok-composer-2.5-fast"),
    ("xai", "grok-4.3"),
    ("xai", "grok-4.20-0309-reasoning"),
    ("xai", "grok-4.20-0309-non-reasoning"),
    ("xai", "grok-3-mini"),
    ("xai", "grok-3-mini-fast"),
)

CAPABILITY_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("zai-coding", "glm-5.2"): {"context": 1_000_000, "output": 131_072, "reasoning": True},
    ("zai-coding", "glm-5.1"): {"context": 200_000, "output": 131_072},
    ("zai-coding", "glm-5"): {"context": 202_752, "output": 131_072},
    ("zai-coding", "glm-4.7"): {"context": 204_800, "output": 131_072},
    ("minimax-coding", "MiniMax-M3"): {"context": 1_000_000, "output": 131_072, "image": True},
    ("minimax-coding", "MiniMax-M2.7"): {"context": 204_800, "output": 131_072},
    ("minimax-coding", "MiniMax-M2.7-highspeed"): {"context": 204_800, "output": 131_072},
    ("opencode-go", "deepseek-v4-pro"): {"context": 1_000_000, "output": 384_000},
    ("opencode-go", "deepseek-v4-flash"): {"context": 1_000_000, "output": 384_000},
    ("opencode-go", "kimi-k2.6"): {"context": 262_144, "output": 65_536, "image": True},
    ("opencode-go", "kimi-k2.5"): {"context": 262_144, "output": 65_536, "image": True},
    ("opencode-go", "glm-5.1"): {"context": 202_752, "output": 32_768},
    ("opencode-go", "glm-5"): {"context": 202_752, "output": 32_768},
    ("opencode-go", "mimo-v2.5-pro"): {"context": 1_048_576, "output": 128_000},
    ("opencode-go", "mimo-v2.5"): {"context": 1_000_000, "output": 128_000, "image": True},
    ("opencode-go", "minimax-m2.7"): {"context": 204_800, "output": 131_072},
    ("opencode-go", "minimax-m2.5"): {"context": 204_800, "output": 65_536},
    ("opencode-go", "qwen3.7-max"): {"context": 1_000_000, "output": 65_536},
    ("opencode-go", "qwen3.6-plus"): {"context": 262_144, "output": 65_536},
    ("opencode-go", "qwen3.5-plus"): {"context": 262_144, "output": 65_536},
    ("opencode-zen", "minimax-m3-free"): {"context": 200_000, "output": 32_000, "image": True},
    ("opencode-zen", "nemotron-3-super-free"): {"context": 204_800, "output": 128_000},
    ("crofai", "kimi-k2.6-precision"): {"context": 262_144, "output": 262_144, "image": True},
    ("xai", "grok-4.3"): {"context": 1_000_000, "output": 30_000, "image": True, "reasoning": True},
    ("xai", "grok-4.20-0309-reasoning"): {
        "context": 2_000_000,
        "output": 30_000,
        "image": True,
        "reasoning": True,
    },
    ("xai", "grok-4.20-0309-non-reasoning"): {"context": 2_000_000, "output": 30_000, "image": True},
    ("cursor-zai-coding", "zai-coding/glm-5.2"): {
        "context": 1_000_000,
        "output": 131_072,
        "reasoning": True,
    },
    ("cursor-zai-coding", "glm-5.2"): {"context": 1_000_000, "output": 131_072, "reasoning": True},
    ("cursor-minimax-coding", "minimax-coding/MiniMax-M3"): {
        "context": 1_000_000,
        "output": 131_072,
        "image": True,
    },
    ("cursor-minimax-coding", "MiniMax-M3"): {"context": 1_000_000, "output": 131_072, "image": True},
    ("commandcode", "MiniMaxAI/MiniMax-M3"): {"context": 1_000_000, "output": 131_072, "image": True},
}


def desktop_models_payload(
    *,
    include_commandcode: bool = True,
    include_cpa_oauth: bool = True,
    cliproxyapi_models: Iterable[dict[str, Any]] | None = None,
    model_overrides: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Return a Codex-compatible model matrix backed by CLIProxyAPI.

    CLIProxyAPI owns provider credentials, OAuth-backed routes, and local
    OpenAI-compatible provider adapters. codex-shim only converts those routes
    into Codex Desktop/CLI catalog rows and adds Codex capability metadata.
    """

    discovered = list(cliproxyapi_models) if cliproxyapi_models is not None else discover_cliproxyapi_models()
    source_rows = discovered or [{"id": model, "owned_by": owner} for owner, model in BOOTSTRAP_MODELS]
    rows = _cliproxyapi_rows(
        source_rows,
        include_commandcode=include_commandcode,
        include_cpa_oauth=include_cpa_oauth,
    )
    _apply_model_overrides(rows, model_overrides or {})
    return {"models": rows}


def write_desktop_models(
    path: Path,
    *,
    include_commandcode: bool = True,
    include_cpa_oauth: bool = True,
    overrides_path: Path | None = None,
) -> Path:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    overrides = load_desktop_model_overrides(overrides_path or desktop_overrides_path(path))
    payload = desktop_models_payload(
        include_commandcode=include_commandcode,
        include_cpa_oauth=include_cpa_oauth,
        model_overrides=overrides,
    )
    _write_json(path, payload)
    return path


def desktop_overrides_path(settings_path: Path) -> Path:
    return Path(settings_path).expanduser().with_name("desktop-model-overrides.json")


def load_desktop_model_overrides(path: Path) -> dict[str, dict[str, int]]:
    path = Path(path).expanduser()
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("models", {}), dict):
        raise ValueError(f"Desktop model overrides must contain a models object: {path}")

    overrides: dict[str, dict[str, int]] = {}
    for slug, raw in payload.get("models", {}).items():
        if not isinstance(slug, str) or not isinstance(raw, dict):
            raise ValueError(f"Desktop model override entries must map slugs to objects: {path}")
        entry: dict[str, int] = {}
        for key in ("auto_compact_token_limit", "truncation_limit"):
            value = _positive_int(raw.get(key))
            if value is not None:
                entry[key] = value
        if entry:
            overrides[slug] = entry
    return overrides


def update_desktop_compaction_override(
    settings_path: Path,
    selector: str,
    *,
    compact_limit: int | None = None,
    truncation_limit: int | None = None,
    clear: bool = False,
    match_all: bool = False,
    overrides_path: Path | None = None,
) -> list[str]:
    settings_path = Path(settings_path).expanduser()
    overrides_path = Path(overrides_path or desktop_overrides_path(settings_path)).expanduser()
    payload = json.loads(settings_path.read_text())
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"Desktop model settings must contain a models array: {settings_path}")

    matches = _matching_model_rows(rows, selector)
    if not matches:
        raise ValueError(f"No desktop model matches selector: {selector}")
    if len(matches) > 1 and not match_all:
        slugs = ", ".join(str(row.get("slug")) for row in matches)
        raise ValueError(f"Selector matches multiple models; use an exact slug or --all: {slugs}")
    if not clear:
        if compact_limit is None and truncation_limit is None:
            raise ValueError("At least one compaction or truncation limit is required")
        if compact_limit is not None and _positive_int(compact_limit) is None:
            raise ValueError("Compaction limit must be a positive integer")
        if truncation_limit is not None and _positive_int(truncation_limit) is None:
            raise ValueError("Truncation limit must be a positive integer")
        for row in matches:
            context_limit = _positive_int(row.get("max_context_limit"))
            effective_compact = compact_limit if compact_limit is not None else _positive_int(row.get("auto_compact_token_limit"))
            effective_truncation = (
                truncation_limit if truncation_limit is not None else _positive_int(row.get("truncation_limit"))
            )
            if context_limit is not None and effective_compact is not None and effective_compact > context_limit:
                raise ValueError(f"Compaction limit exceeds context window for {row['slug']}: {effective_compact} > {context_limit}")
            if effective_compact is not None and effective_truncation is not None and effective_truncation > effective_compact:
                raise ValueError(
                    f"Truncation limit exceeds compaction limit for {row['slug']}: "
                    f"{effective_truncation} > {effective_compact}"
                )

    stored = _read_override_document(overrides_path)
    stored_models = stored.setdefault("models", {})
    changed_slugs: list[str] = []
    for row in matches:
        slug = str(row["slug"])
        changed_slugs.append(slug)
        if clear:
            previous = stored_models.pop(slug, {})
            for key in ("auto_compact_token_limit", "truncation_limit"):
                prior_value = _positive_int(previous.get(f"previous_{key}")) if isinstance(previous, dict) else None
                if prior_value is not None:
                    row[key] = prior_value
            continue

        existing = stored_models.get(slug)
        entry = dict(existing) if isinstance(existing, dict) else {}
        if compact_limit is not None:
            entry.setdefault("previous_auto_compact_token_limit", row.get("auto_compact_token_limit"))
            entry["auto_compact_token_limit"] = compact_limit
            row["auto_compact_token_limit"] = compact_limit
        if truncation_limit is not None:
            entry.setdefault("previous_truncation_limit", row.get("truncation_limit"))
            entry["truncation_limit"] = truncation_limit
            row["truncation_limit"] = truncation_limit
        stored_models[slug] = entry

    _write_json(settings_path, payload)
    _write_json(overrides_path, stored)
    return changed_slugs


def _matching_model_rows(rows: list[Any], selector: str) -> list[dict[str, Any]]:
    candidates = [row for row in rows if isinstance(row, dict) and isinstance(row.get("slug"), str)]
    exact_slug = [row for row in candidates if row["slug"] == selector]
    if exact_slug:
        return exact_slug
    exact_model = [row for row in candidates if row.get("model") == selector]
    if exact_model:
        return exact_model
    normalized = selector.casefold()
    return [
        row
        for row in candidates
        if isinstance(row.get("display_name"), str) and row["display_name"].casefold() == normalized
    ]


def _read_override_document(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {"models": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("models", {}), dict):
        raise ValueError(f"Desktop model overrides must contain a models object: {path}")
    return payload


def _apply_model_overrides(rows: list[dict[str, Any]], overrides: dict[str, dict[str, int]]) -> None:
    for row in rows:
        override = overrides.get(str(row.get("slug") or ""))
        if not override:
            continue
        for key in ("auto_compact_token_limit", "truncation_limit"):
            value = _positive_int(override.get(key))
            if value is not None:
                row[key] = value


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(path)


def discover_cliproxyapi_models(
    *,
    base_url: str = CLIPROXYAPI_BASE_URL,
    api_key: str | None = None,
    timeout: float = DISCOVERY_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    api_key = _cliproxyapi_discovery_api_key(api_key)
    if not api_key:
        return []
    url = base_url.rstrip("/") + "/models"
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        preserved = dict(item)
        preserved["id"] = model_id
        preserved["owned_by"] = str(item.get("owned_by") or "cliproxyapi").strip()
        rows.append(preserved)
    return rows


def _cliproxyapi_discovery_api_key(explicit: str | None = None) -> str:
    if explicit is not None:
        return explicit.strip()
    env_value = os.environ.get(CLIPROXYAPI_CREDENTIAL, "").strip()
    if env_value:
        return env_value
    credentials_dir = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if not credentials_dir:
        return ""
    try:
        return (Path(credentials_dir) / CLIPROXYAPI_CREDENTIAL).read_text().strip()
    except OSError:
        return ""


def _cliproxyapi_rows(
    rows: Iterable[dict[str, Any]],
    *,
    include_commandcode: bool,
    include_cpa_oauth: bool,
) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for index, row in enumerate(rows):
        model_id = str(row.get("id") or row.get("model") or "").strip()
        owner = str(row.get("owned_by") or row.get("owner") or "cliproxyapi").strip() or "cliproxyapi"
        if (
            not model_id
            or not _include_owner(owner, include_commandcode=include_commandcode, include_cpa_oauth=include_cpa_oauth)
            or not _looks_like_chat_model(model_id)
        ):
            continue
        generated_row = _row_from_cliproxyapi(owner=owner, model_id=model_id, index=index, raw=row)
        slug = generated_row["slug"]
        if slug in seen_slugs:
            slug = f"{slug}-{index}"
            generated_row["slug"] = slug
        seen_slugs.add(slug)
        generated.append(generated_row)
    return generated


def _include_owner(owner: str, *, include_commandcode: bool, include_cpa_oauth: bool) -> bool:
    normalized = owner.strip().lower()
    if normalized in SKIPPED_DISCOVERY_OWNERS:
        return False
    if not include_commandcode and normalized == "commandcode":
        return False
    if not include_cpa_oauth and normalized == "xai":
        return False
    return True


def _looks_like_chat_model(model_id: str) -> bool:
    lower = model_id.lower()
    return not any(marker in lower for marker in NON_CHAT_MODEL_MARKERS)


def _row_from_cliproxyapi(*, owner: str, model_id: str, index: int, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    caps = _capabilities(owner, model_id, raw=raw)
    route_label = _route_label(owner)
    return {
        "slug": _route_slug(owner, model_id),
        "model": model_id,
        "display_name": _display_name(owner, model_id),
        "provider": "generic-chat-completion-api",
        "provider_display_name": f"CLIProxyAPI / {route_label}",
        "base_url": CLIPROXYAPI_BASE_URL,
        "api_key_credential": CLIPROXYAPI_CREDENTIAL,
        "max_context_limit": caps["context"],
        "max_output_tokens": caps["output"],
        "auto_compact_token_limit": caps["compact"] or _ratio_limit(
            caps["context"],
            env_name="CODEX_SHIM_AUTO_COMPACT_RATIO",
            default_ratio=0.82,
            minimum=8_000,
            maximum=None,
        ),
        "truncation_limit": caps["truncation"] or _ratio_limit(
            caps["context"],
            env_name="CODEX_SHIM_TRUNCATION_RATIO",
            default_ratio=0.22,
            minimum=16_000,
            maximum=128_000,
        ),
        "no_image_support": not caps["image"],
        "supports_tools": caps["tools"],
        "supports_reasoning": caps["reasoning"],
        "supports_streaming": caps["streaming"],
        "index": index,
        "generated_by": "codex-shim-cliproxyapi-discovery",
    }


def _route_label(owner: str) -> str:
    label = OWNER_LABELS.get(owner)
    if label is not None:
        return label
    if owner.startswith("cursor-"):
        source_owner = owner.removeprefix("cursor-")
        return OWNER_LABELS.get(source_owner, _label_from_slug(source_owner))
    return _label_from_slug(owner)


def _capabilities(owner: str, model_id: str, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    caps = {
        "context": 128_000,
        "output": 32_768,
        "image": False,
        "tools": owner in TOOL_CAPABLE_OWNERS,
        "reasoning": False,
        "streaming": True,
        "compact": None,
        "truncation": None,
    }
    if owner == "xai":
        caps.update({"context": 200_000, "output": 30_000, "image": model_id.startswith("grok-4")})
    caps.update(CAPABILITY_OVERRIDES.get((owner, model_id), {}))
    if raw is not None:
        raw_context = _raw_int(
            raw,
            "max_context_limit",
            "maxContextLimit",
            "context_window",
            "contextWindow",
            "max_context_window",
            "maxContextWindow",
            "context_length",
            "contextLength",
            "context_size",
            "contextSize",
            "max_input_tokens",
            "maxInputTokens",
        )
        if raw_context is not None:
            caps["context"] = raw_context
        raw_output = _raw_int(
            raw,
            "max_output_tokens",
            "maxOutputTokens",
            "max_tokens",
            "maxTokens",
            "output_tokens",
            "outputTokens",
        )
        if raw_output is not None:
            caps["output"] = raw_output
        raw_compact = _raw_int(raw, "auto_compact_token_limit", "autoCompactTokenLimit", "compact_tokens", "compactTokens")
        if raw_compact is not None:
            caps["compact"] = raw_compact
        raw_truncation = _raw_int(raw, "truncation_limit", "truncationLimit", "truncation_tokens", "truncationTokens")
        if raw_truncation is not None:
            caps["truncation"] = raw_truncation
        raw_tools = _raw_bool(raw, "supports_tools", "supportsTools", "tool_calls", "toolCalls")
        if raw_tools is not None:
            caps["tools"] = raw_tools
        raw_streaming = _raw_bool(raw, "supports_streaming", "supportsStreaming")
        if raw_streaming is not None:
            caps["streaming"] = raw_streaming
        raw_image = _raw_bool(raw, "supports_image_inputs", "supportsImageInputs", "supports_images", "supportsImages", "image", "vision", "multimodal")
        if raw_image is not None:
            caps["image"] = raw_image
        raw_no_image = _raw_bool(raw, "no_image_support", "noImageSupport")
        if raw_no_image is not None:
            caps["image"] = not raw_no_image
        raw_reasoning = _raw_bool(raw, "supports_reasoning", "supportsReasoning", "reasoning")
        if raw_reasoning is not None:
            caps["reasoning"] = raw_reasoning
    return caps


def _raw_bool(row: dict[str, Any], *keys: str) -> bool | None:
    for source in _raw_sources(row):
        for key in keys:
            if key not in source:
                continue
            value = source[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"1", "true", "yes", "on"}:
                    return True
                if lowered in {"0", "false", "no", "off"}:
                    return False
            if isinstance(value, (int, float)):
                return bool(value)
    return None


def _raw_int(row: dict[str, Any], *keys: str) -> int | None:
    for source in _raw_sources(row):
        for key in keys:
            if key not in source:
                continue
            value = source[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                return value if value > 0 else None
            if isinstance(value, float):
                return int(value) if value > 0 else None
            if isinstance(value, str):
                normalized = value.strip().replace(",", "").replace("_", "")
                if normalized.isdigit():
                    parsed = int(normalized)
                    return parsed if parsed > 0 else None
    return None


def _raw_sources(row: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield row
    for key in ("metadata", "capabilities", "limits"):
        value = row.get(key)
        if isinstance(value, dict):
            yield value


def _ratio_limit(
    context: int,
    *,
    env_name: str,
    default_ratio: float,
    minimum: int,
    maximum: int | None,
) -> int:
    ratio = _env_ratio(env_name, default_ratio)
    value = max(minimum, int(context * ratio))
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_ratio(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, 1.0)


def _route_slug(owner: str, model_id: str) -> str:
    model_slug = _slugify(model_id.rsplit("/", 1)[-1])
    owner_slug = _slugify(owner)
    if owner == "xai" and model_slug.startswith("grok-"):
        return model_slug
    return f"{owner_slug}-{model_slug}"


def _display_name(owner: str, model_id: str) -> str:
    value = model_id.rsplit("/", 1)[-1]
    if owner == "xai":
        value = model_id
    return _label_from_slug(value)


def _label_from_slug(value: str) -> str:
    words = re.split(r"[-_]+", value.strip())
    return " ".join(_format_word(word) for word in words if word)


def _format_word(word: str) -> str:
    lower = word.lower()
    if lower in {"ai", "api", "cli", "oauth"}:
        return lower.upper()
    if lower == "zai":
        return "Z.ai"
    if lower == "xai":
        return "xAI"
    if lower == "glm":
        return "GLM"
    if lower == "mimo":
        return "MiMo"
    if lower == "minimax":
        return "MiniMax"
    if lower == "deepseek":
        return "DeepSeek"
    if lower == "qwen":
        return "Qwen"
    if lower == "kimi":
        return "Kimi"
    if lower == "grok":
        return "Grok"
    if re.fullmatch(r"v2(?:\.\d+)?", lower):
        return lower
    if re.fullmatch(r"[vmkq]\d+(?:\.\d+)?", lower):
        return lower.upper()
    if re.fullmatch(r"qwen\d+(?:\.\d+)?", lower):
        return "Qwen" + lower[4:]
    return word[:1].upper() + word[1:]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "model"
