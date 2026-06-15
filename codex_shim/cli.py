from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import time
import hashlib
import json
import shutil
import tomllib
from urllib.request import urlopen

from . import router as router_module
from .catalog import _toml_escape, codex_config_overrides, write_catalog, write_config
from .cursor_passthrough import (
    cursor_passthrough_available,
    cursor_passthrough_display_names,
    is_cursor_passthrough_slug,
)
from .settings import (
    CHATGPT_MODEL_SLUG,
    DEFAULT_SETTINGS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    PROVIDER_NAME,
    ModelSettings,
    available_model_slugs,
    chatgpt_passthrough_available,
    chatgpt_passthrough_display_names,
    chatgpt_passthrough_slugs,
    default_model_slug,
    is_chatgpt_passthrough_slug,
    usable_byok_models,
    byok_model_has_credentials,
)
from .desktop_models import (
    desktop_overrides_path,
    load_desktop_model_overrides,
    update_desktop_compaction_override,
    write_desktop_models,
)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_runtime_dir() -> Path:
    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        return Path(xdg_state_home).expanduser() / "codex-shim"
    return Path.home() / ".local" / "state" / "codex-shim"


PROJECT_ROOT = Path(os.environ.get("CODEX_SHIM_PROJECT_ROOT") or _default_project_root()).expanduser()
RUNTIME_DIR = Path(os.environ.get("CODEX_SHIM_RUNTIME_DIR") or _default_runtime_dir()).expanduser()
CATALOG_PATH = RUNTIME_DIR / "custom_model_catalog.json"
CONFIG_PATH = RUNTIME_DIR / "config.toml"
PID_PATH = RUNTIME_DIR / "shim.pid"
LOG_PATH = RUNTIME_DIR / "shim.log"
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
CODEX_CONFIG_BACKUP_PATH = RUNTIME_DIR / "config.toml.before-codex-shim"
CODEX_SHIM_PROFILE_NAME = "codex-shim"
CODEX_SHIM_PROFILE_PATH = Path.home() / ".codex" / f"{CODEX_SHIM_PROFILE_NAME}.config.toml"
CODEX_SHIM_PROFILE_CLI_PATH = Path.home() / ".local" / "bin" / "codex-shim-profile-codex"
CODEX_SHIM_DESKTOP_WRAPPER_PATH = Path.home() / ".local" / "bin" / "codex-desktop-shim"
MANAGED_BEGIN = "# >>> codex-shim managed >>>"
MANAGED_END = "# <<< codex-shim managed <<<"
PREVIOUS_TOP_LEVEL_PREFIX = "# codex-shim previous-top-level = "
MANAGED_TOP_LEVEL_KEYS = {"model", "model_provider", "model_catalog_json"}
HEALTH_CHECK_TIMEOUT_SECONDS = 3.0
LINUX_SYSTEM_CODEX_APP = Path("/opt/codex-desktop")
LINUX_USER_CODEX_APP = Path.home() / ".local" / "share" / "codex-desktop-linux-overlay" / "patched-app"
LINUX_SOURCE_HASH_STAMP = ".codex-shim-source-app-asar-sha256"
MODEL_PICKER_PATCH_VARIANTS = [
    (
        ["models-and-reasoning-efforts-*.js", "model-queries-*.js", "*.js"],
        "let a=[],o=null,s=i&&e!==`amazonBedrock`;",
        "let a=[],o=null,s=!1;",
    ),
    (
        ["model-queries-*.js", "*.js"],
        "let u=c.useHiddenModels&&o!==`amazonBedrock`,d;",
        "let u=!1,d;",
    ),
]
SIDEBAR_RECENT_THREADS_PATCH_VARIANTS = [
    (
        ["app-server-manager-signals-*.js", "*.js"],
        "listRecentThreads({cursor:e,limit:t}){return this.params.requestClient.sendRequest(`thread/list`,"
        "{limit:t,cursor:e,sortKey:this.recentConversationSortKey,modelProviders:null,archived:!1,sourceKinds:he})}",
        "listRecentThreads({cursor:e,limit:t}){return this.params.requestClient.sendRequest(`thread/list`,"
        "{limit:t,cursor:e,sortKey:this.recentConversationSortKey,modelProviders:[],archived:!1,sourceKinds:he})}",
    ),
    (
        ["app-server-manager-signals-*.js", "*.js"],
        "listRecentThreads({cursor:e,limit:t}){return this.params.requestClient.sendRequest(`thread/list`,"
        "{limit:t,cursor:e,sortKey:this.recentConversationSortKey,modelProviders:null,archived:!1,sourceKinds:ke})}",
        "listRecentThreads({cursor:e,limit:t}){return this.params.requestClient.sendRequest(`thread/list`,"
        "{limit:t,cursor:e,sortKey:this.recentConversationSortKey,modelProviders:[],archived:!1,sourceKinds:ke})}",
    ),
]
MODEL_PICKER_REPLACEMENTS = tuple(replacement for _, _, replacement in MODEL_PICKER_PATCH_VARIANTS)
SIDEBAR_RECENT_THREADS_REPLACEMENTS = tuple(
    replacement for _, _, replacement in SIDEBAR_RECENT_THREADS_PATCH_VARIANTS
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-shim")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    sub.add_parser("list")
    sub.add_parser("start")
    sub.add_parser("enable")
    sub.add_parser("stop")
    sub.add_parser("disable")
    sub.add_parser("restart")
    sub.add_parser("status")
    doctor_parser = sub.add_parser("doctor", help="Check catalog, service, and first-party routing safety.")
    doctor_parser.add_argument("--json", action="store_true", dest="json_output")
    sub.add_parser("patch-app", help="Patch Linux Codex Desktop picker/sidebar handling for custom shim models.")
    sub.add_parser("restore-app", help="Restore Linux Codex Desktop app.asar from the pre-patch backup.")

    model_parser = sub.add_parser("model", help="List or set the active shim model in Codex config.")
    model_sub = model_parser.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("list")
    use_parser = model_sub.add_parser("use")
    use_parser.add_argument("model_slug")

    codex_parser = sub.add_parser("codex", help="Run Codex CLI with opt-in shim config overrides.")
    codex_parser.add_argument("args", nargs=argparse.REMAINDER)

    app_parser = sub.add_parser("app", help="Launch Linux Codex Desktop with opt-in shim config overrides.")
    app_parser.add_argument("-m", "--model", dest="model_slug")
    app_parser.add_argument("path", nargs="?", default=".")

    desktop_parser = sub.add_parser("desktop", help="Linux Codex Desktop model matrix helpers.")
    desktop_sub = desktop_parser.add_subparsers(dest="desktop_command", required=True)
    desktop_write = desktop_sub.add_parser("write-models", help="Write CLIProxyAPI-backed models.json for Desktop.")
    desktop_write.add_argument("--output", type=Path, default=DEFAULT_SETTINGS)
    desktop_write.add_argument("--no-commandcode", action="store_true", help="Omit CLIProxyAPI CommandCode routes.")
    desktop_write.add_argument("--no-cpa-oauth", action="store_true", help="Omit CLIProxyAPI OAuth-only routes such as Grok CLI.")
    compaction_parser = desktop_sub.add_parser(
        "compaction",
        help="Persist per-model Desktop compaction and truncation thresholds.",
    )
    compaction_sub = compaction_parser.add_subparsers(dest="compaction_command", required=True)
    compaction_set = compaction_sub.add_parser("set", help="Set thresholds by model slug, upstream id, or display name.")
    compaction_set.add_argument("selector")
    compaction_set.add_argument("compact_limit", type=_token_count)
    compaction_set.add_argument("--truncation", type=_token_count, dest="truncation_limit")
    compaction_set.add_argument("--all", action="store_true", dest="match_all", help="Update every row matching an upstream id or display name.")
    compaction_clear = compaction_sub.add_parser("clear", help="Remove persisted thresholds by slug, upstream id, or display name.")
    compaction_clear.add_argument("selector")
    compaction_clear.add_argument("--all", action="store_true", dest="match_all", help="Clear every row matching an upstream id or display name.")
    compaction_sub.add_parser("list", help="List persisted per-model threshold overrides.")

    args = parser.parse_args(argv)
    if args.command == "generate":
        generate(args.settings, args.port)
        return 0
    if args.command == "list":
        return list_models(args.settings)
    if args.command in {"start", "enable"}:
        generate(args.settings, args.port)
        code = start(args.settings, args.port)
        if code == 0 and args.command == "enable":
            install_codex_profile_config(args.settings, args.port)
        return code
    if args.command in {"stop", "disable"}:
        if args.command == "disable":
            restore_codex_config()
            remove_codex_profile_config()
        return stop()
    if args.command == "restart":
        stop()
        generate(args.settings, args.port)
        return start(args.settings, args.port)
    if args.command == "status":
        return status(args.port)
    if args.command == "doctor":
        return doctor(args.settings, args.port, json_output=args.json_output)
    if args.command == "patch-app":
        return patch_codex_app()
    if args.command == "restore-app":
        return restore_codex_app_bundle()
    if args.command == "model":
        if args.model_command == "list":
            return list_models(args.settings)
        if args.model_command == "use":
            generate(args.settings, args.port)
            ensure_started(args.settings, args.port)
            install_codex_profile_config(args.settings, args.port, args.model_slug)
            print(f"Active Codex shim profile model: {args.model_slug}")
            return 0
    if args.command == "codex":
        generate(args.settings, args.port)
        ensure_started(args.settings, args.port)
        exec_codex(args.settings, args.port, args.args)
        return 0
    if args.command == "app":
        generate(args.settings, args.port)
        ensure_started(args.settings, args.port)
        install_codex_profile_config(args.settings, args.port, args.model_slug)
        exec_codex_app(args.settings, args.port, args.path, shim_profile=True)
        return 0
    if args.command == "desktop" and args.desktop_command == "write-models":
        output = write_desktop_models(
            args.output,
            include_commandcode=not args.no_commandcode,
            include_cpa_oauth=not args.no_cpa_oauth,
        )
        print(f"Wrote desktop model matrix to {output}")
        return 0
    if args.command == "desktop" and args.desktop_command == "compaction":
        overrides_path = desktop_overrides_path(args.settings)
        if args.compaction_command == "list":
            overrides = load_desktop_model_overrides(overrides_path)
            if not overrides:
                print(f"No desktop compaction overrides in {overrides_path}.")
                return 0
            for slug, values in sorted(overrides.items()):
                compact = values.get("auto_compact_token_limit", "default")
                truncation = values.get("truncation_limit", "default")
                print(f"{slug}: compact={compact} truncation={truncation}")
            return 0
        try:
            changed = update_desktop_compaction_override(
                args.settings,
                args.selector,
                compact_limit=getattr(args, "compact_limit", None),
                truncation_limit=getattr(args, "truncation_limit", None),
                clear=args.compaction_command == "clear",
                match_all=args.match_all,
                overrides_path=overrides_path,
            )
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            print(f"Could not update desktop compaction policy: {exc}", file=sys.stderr)
            return 2
        action = "Cleared" if args.compaction_command == "clear" else "Updated"
        print(f"{action} desktop compaction policy for: {', '.join(changed)}")
        print(f"Settings:  {Path(args.settings).expanduser()}")
        print(f"Overrides: {overrides_path}")
        print("Restart codex-shim so Desktop receives the updated catalog.")
        return 0
    return 2


def _token_count(raw: str) -> int:
    value = raw.strip().lower().replace("_", "").replace(",", "")
    multiplier = 1
    if value.endswith("k"):
        multiplier = 1_000
        value = value[:-1]
    elif value.endswith("m"):
        multiplier = 1_000_000
        value = value[:-1]
    try:
        parsed = float(value) * multiplier
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid token count: {raw}") from exc
    if parsed <= 0 or not parsed.is_integer():
        raise argparse.ArgumentTypeError(f"token count must be a positive whole number: {raw}")
    return int(parsed)


def _load_models(settings_path: Path):
    expanded = Path(settings_path).expanduser()
    try:
        return ModelSettings(expanded).load()
    except FileNotFoundError as exc:
        raise SystemExit(
            f"Settings file not found: {expanded}\n"
            "Create ~/.codex-shim/models.json, or pass --settings /path/to/models.json."
        ) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Settings file is not valid JSON: {expanded}: {exc}") from exc


def _active_router(models, settings_path: Path):
    """RouterConfig when the Auto Router is enabled and has a usable candidate."""
    config = router_module.load_router_config(Path(settings_path).expanduser())
    if config and router_module.router_is_active(config, available_model_slugs(models)):
        return config
    return None


def generate(settings_path: Path, port: int) -> None:
    models = _load_models(settings_path)
    try:
        default_model_slug(models)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    router_config = router_module.load_router_config(Path(settings_path).expanduser())
    write_catalog(models, CATALOG_PATH, router_config=router_config)
    write_config(models, CONFIG_PATH, CATALOG_PATH, port)
    print(f"Generated {len(models)} model entries:")
    if _active_router(models, settings_path) is not None:
        print(f"  auto router: {router_config.slug} ({router_config.display_name})")
    print(f"  catalog: {CATALOG_PATH}")
    print(f"  config:  {CONFIG_PATH}")
    print("No files under ~/.codex were modified.")


def install_codex_config(settings_path: Path, port: int, model_slug: str | None = None) -> None:
    models = _load_models(settings_path)
    router_config = _active_router(models, settings_path)
    default_slug = _resolve_model_slug(models, model_slug, router_config)
    CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    original = CODEX_CONFIG_PATH.read_text() if CODEX_CONFIG_PATH.exists() else ""
    cleaned = _remove_managed_config(original)
    current_top_level = _extract_top_level_key_lines(cleaned, MANAGED_TOP_LEVEL_KEYS)
    if current_top_level:
        previous_top_level = current_top_level
    else:
        previous_top_level = _managed_previous_top_level(original)
    if not previous_top_level and CODEX_CONFIG_BACKUP_PATH.exists():
        previous_top_level = _extract_top_level_key_lines(CODEX_CONFIG_BACKUP_PATH.read_text(), MANAGED_TOP_LEVEL_KEYS)
    cleaned = _remove_top_level_keys(cleaned, MANAGED_TOP_LEVEL_KEYS)
    cleaned = _remove_section(cleaned, f"model_providers.{PROVIDER_NAME}")
    provider_name = _provider_display_name(models, default_slug, router_config)
    top_block, provider_block = _managed_config_blocks(
        default_slug, port, previous_top_level, provider_name=provider_name
    )
    CODEX_CONFIG_PATH.write_text(top_block + "\n" + cleaned.lstrip() + "\n" + provider_block)
    print(f"Installed shim config into {CODEX_CONFIG_PATH}.")


def install_codex_profile_config(settings_path: Path, port: int, model_slug: str | None = None) -> None:
    models = _load_models(settings_path)
    router_config = _active_router(models, settings_path)
    default_slug = _resolve_model_slug(models, model_slug, router_config)
    CODEX_SHIM_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_name = _provider_display_name(models, default_slug, router_config)
    top_block, provider_block = _managed_config_blocks(
        default_slug,
        port,
        previous_top_level=None,
        provider_name=provider_name,
    )
    CODEX_SHIM_PROFILE_PATH.write_text(top_block + "\n" + provider_block)
    _write_profile_wrappers(default_slug, provider_name, port)
    print(f"Installed shim profile config into {CODEX_SHIM_PROFILE_PATH}.")


def list_models(settings_path: Path) -> int:
    models = _load_models(settings_path)
    rows: list[tuple[str, str, str, str]] = []
    router_config = _active_router(models, settings_path)
    if router_config is not None:
        rows.append((router_config.slug, router_config.display_name, "per-task pick", "auto"))
    if chatgpt_passthrough_available():
        for slug, display_name in chatgpt_passthrough_display_names().items():
            rows.append((slug, display_name, slug, "chatgpt"))
    if cursor_passthrough_available():
        for slug, display_name in cursor_passthrough_display_names().items():
            rows.append((slug, display_name, "composer-2.5", "cursor-subscription"))
    rows.extend((model.slug, model.display_name, model.model, model.provider) for model in usable_byok_models(models))
    for model in models:
        if model not in usable_byok_models(models):
            rows.append((model.slug, f"{model.display_name} (missing API key)", model.model, model.provider))
    if not rows:
        print(
            "No models available. Create ~/.codex-shim/models.json, pass --settings /path/to/models.json, "
            "run `codex login` for GPT passthrough, or run `cursor-agent login` for Composer passthrough.",
            file=sys.stderr,
        )
        return 1
    width = max(len(row[0]) for row in rows)
    for slug, display_name, model, provider in rows:
        print(f"{slug:<{width}}  {display_name}  ->  {model} ({provider})", flush=True)
    return 0


def start(settings_path: Path, port: int) -> int:
    if _pid_running(_read_pid()):
        print(f"Shim already running with pid {_read_pid()}.")
        return 0
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("ab")
    cmd = [
        sys.executable,
        "-m",
        "codex_shim.server",
        "--settings",
        str(settings_path),
        "--host",
        DEFAULT_HOST,
        "--port",
        str(port),
    ]
    env = os.environ.copy()
    env["CODEX_SHIM_RUNTIME_DIR"] = str(RUNTIME_DIR)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    process = _popen_daemon(cmd, log, env)
    PID_PATH.write_text(str(process.pid))
    for _ in range(50):
        if _healthy(port):
            print(f"Shim started on http://{DEFAULT_HOST}:{port} with pid {process.pid}.")
            print(f"Log: {LOG_PATH}")
            return 0
        if process.poll() is not None:
            print(f"Shim exited during startup. See {LOG_PATH}.", file=sys.stderr)
            return 1
        time.sleep(0.1)
    print(f"Shim process started but health check timed out. See {LOG_PATH}.", file=sys.stderr)
    return 1


def stop() -> int:
    pid = _read_pid()
    if not _pid_running(pid):
        print("Shim is not running.")
        PID_PATH.unlink(missing_ok=True)
        return 0
    _terminate_pid(pid)
    for _ in range(50):
        if not _pid_running(pid):
            PID_PATH.unlink(missing_ok=True)
            print("Shim stopped.")
            return 0
        time.sleep(0.1)
    print(f"Shim pid {pid} did not exit after SIGTERM.", file=sys.stderr)
    return 1


def restore_codex_config() -> None:
    if CODEX_CONFIG_PATH.exists():
        current = CODEX_CONFIG_PATH.read_text()
        previous_top_level = _managed_previous_top_level(current)
        if not previous_top_level and CODEX_CONFIG_BACKUP_PATH.exists():
            previous_top_level = _extract_top_level_key_lines(CODEX_CONFIG_BACKUP_PATH.read_text(), MANAGED_TOP_LEVEL_KEYS)
        restored = _remove_managed_config(current)
        restored = _remove_section(restored, f"model_providers.{PROVIDER_NAME}")
        restored = _restore_missing_top_level_keys(restored.lstrip(), previous_top_level)
        CODEX_CONFIG_PATH.write_text(restored)
        print(f"Removed shim config from {CODEX_CONFIG_PATH}.")
    if CODEX_CONFIG_BACKUP_PATH.exists():
        CODEX_CONFIG_BACKUP_PATH.unlink()
        print(f"Removed stale shim backup {CODEX_CONFIG_BACKUP_PATH}.")


def remove_codex_profile_config() -> None:
    for path in (CODEX_SHIM_PROFILE_PATH, CODEX_SHIM_PROFILE_CLI_PATH, CODEX_SHIM_DESKTOP_WRAPPER_PATH):
        if path.exists():
            path.unlink()
            print(f"Removed {path}.")


def status(port: int) -> int:
    pid = _read_pid()
    if _pid_running(pid):
        health = _health(port)
        if health is not None:
            model_count = health.get("models", "unknown")
            print(f"Shim is running on http://{DEFAULT_HOST}:{port} with pid {pid} ({model_count} models).")
            return 0
    if _pid_running(pid):
        print(f"Shim process {pid} exists but health check failed.")
        return 1
    print("Shim is stopped.")
    return 1


def doctor(settings_path: Path, port: int, *, json_output: bool = False) -> int:
    checks: list[dict[str, str]] = []

    def record(check_id: str, status_value: str, detail: str) -> None:
        checks.append({"id": check_id, "status": status_value, "detail": detail})

    expanded_settings = Path(settings_path).expanduser()
    try:
        models = ModelSettings(expanded_settings).load()
        if models:
            record("settings", "pass", f"{expanded_settings} contains {len(models)} model rows")
        else:
            record("settings", "fail", f"{expanded_settings} contains no model rows")
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        record("settings", "fail", f"could not load {expanded_settings}: {exc}")

    overrides_path = desktop_overrides_path(expanded_settings)
    try:
        overrides = load_desktop_model_overrides(overrides_path)
        if overrides_path.exists():
            record("compaction-overrides", "pass", f"{overrides_path} contains {len(overrides)} overrides")
        else:
            record("compaction-overrides", "info", f"no override file at {overrides_path}")
    except (json.JSONDecodeError, ValueError) as exc:
        record("compaction-overrides", "fail", f"could not load {overrides_path}: {exc}")

    health = _health(port)
    if health is None:
        record("health", "fail", f"http://{DEFAULT_HOST}:{port}/health is unavailable")
    else:
        record("health", "pass", f"shim is healthy with {health.get('models', 'unknown')} models")

    if CODEX_CONFIG_PATH.exists():
        try:
            config = tomllib.loads(CODEX_CONFIG_PATH.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            record("official-routing", "fail", f"could not parse {CODEX_CONFIG_PATH}: {exc}")
        else:
            default_provider = config.get("model_provider")
            if default_provider == PROVIDER_NAME:
                record("official-routing", "fail", f"{CODEX_CONFIG_PATH} sets the global provider to {PROVIDER_NAME}")
            else:
                record("official-routing", "pass", f"global provider is {default_provider or 'unset'}, not {PROVIDER_NAME}")

            providers = config.get("model_providers")
            shim_provider = providers.get(PROVIDER_NAME) if isinstance(providers, dict) else None
            if not isinstance(shim_provider, dict):
                record("desktop-provider", "info", f"no durable [model_providers.{PROVIDER_NAME}] block is configured")
            elif (
                shim_provider.get("base_url") == f"http://{DEFAULT_HOST}:{port}/v1"
                and shim_provider.get("wire_api") == "responses"
            ):
                record("desktop-provider", "pass", "durable Desktop provider points to the loopback Responses endpoint")
            else:
                record("desktop-provider", "fail", f"[model_providers.{PROVIDER_NAME}] does not match the local Responses endpoint")
    else:
        record("official-routing", "info", f"{CODEX_CONFIG_PATH} does not exist")
        record("desktop-provider", "info", f"no durable [model_providers.{PROVIDER_NAME}] block is configured")

    counts = {status_value: sum(check["status"] == status_value for check in checks) for status_value in ("pass", "info", "fail")}
    payload = {"ready": counts["fail"] == 0, "counts": counts, "checks": checks}
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for check in checks:
            print(f"[{check['status'].upper()}] {check['id']}: {check['detail']}")
        print(f"Summary: {counts['pass']} pass, {counts['info']} info, {counts['fail']} fail")
    return 0 if payload["ready"] else 1


def ensure_started(settings_path: Path, port: int) -> None:
    if not (_pid_running(_read_pid()) and _healthy(port)):
        code = start(settings_path, port)
        if code:
            raise SystemExit(code)


def exec_codex(settings_path: Path, port: int, codex_args: list[str]) -> None:
    overrides = _override_args(settings_path, port)
    codex_args = list(codex_args or [])
    if codex_args[:1] == ["--"]:
        codex_args = codex_args[1:]
    args = ["codex", *overrides, *codex_args]
    env = _with_loopback_no_proxy(os.environ.copy())
    os.execvpe("codex", args, env)


def exec_codex_app(settings_path: Path, port: int, path: str, *, shim_profile: bool = False) -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("codex-shim app is Linux-only in this fork.")
    _quit_linux_codex_desktop()
    if shim_profile:
        _write_profile_wrappers()
    args = _linux_codex_desktop_command(path, shim_profile=shim_profile)
    subprocess.Popen(args, env=_with_loopback_no_proxy(os.environ.copy()))


def _with_loopback_no_proxy(env: dict[str, str]) -> dict[str, str]:
    loopback = ["127.0.0.1", "localhost", "::1"]
    for key in ("NO_PROXY", "no_proxy"):
        values = [part.strip() for part in env.get(key, "").split(",") if part.strip()]
        lower_values = {value.lower() for value in values}
        for host in loopback:
            if host.lower() not in lower_values:
                values.append(host)
        env[key] = ",".join(values)
    return env


def _linux_codex_desktop_command(path: str = ".", *, shim_profile: bool = False) -> list[str]:
    launcher = os.environ.get("CODEX_DESKTOP_LINUX_LAUNCHER")
    if launcher:
        return [launcher, path]

    if shim_profile and CODEX_SHIM_DESKTOP_WRAPPER_PATH.exists():
        return [str(CODEX_SHIM_DESKTOP_WRAPPER_PATH), path]

    user_wrapper = Path.home() / ".local" / "bin" / "codex-desktop-patched"
    if user_wrapper.exists():
        return [str(user_wrapper), path]

    patched_start = LINUX_USER_CODEX_APP / "start.sh"
    if patched_start.exists():
        return [str(patched_start), "--x11", path]

    system_launcher = shutil.which("codex-desktop") or "/usr/bin/codex-desktop"
    return [system_launcher, "--x11", path]


def _write_profile_wrappers(
    model_slug: str | None = None,
    provider_name: str | None = None,
    port: int | None = None,
) -> None:
    model_slug, provider_name, port = _profile_wrapper_values(model_slug, provider_name, port)
    overrides = [
        f'model="{_toml_escape(model_slug)}"',
        f'model_provider="{PROVIDER_NAME}"',
        f'model_catalog_json="{_toml_escape(str(CATALOG_PATH))}"',
        f'model_providers.{PROVIDER_NAME}.name="{_toml_escape(provider_name)}"',
        f'model_providers.{PROVIDER_NAME}.base_url="http://127.0.0.1:{port}/v1"',
        f'model_providers.{PROVIDER_NAME}.wire_api="responses"',
        f'model_providers.{PROVIDER_NAME}.experimental_bearer_token="dummy"',
        f'model_providers.{PROVIDER_NAME}.request_max_retries=3',
        f'model_providers.{PROVIDER_NAME}.stream_max_retries=3',
        f'model_providers.{PROVIDER_NAME}.stream_idle_timeout_ms=600000',
    ]
    override_lines = "".join(f"  -c {shlex.quote(pair)} \\\n" for pair in overrides)
    CODEX_SHIM_PROFILE_CLI_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_SHIM_PROFILE_CLI_PATH.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'CODEX_BIN="${CODEX_SHIM_CODEX_CLI:-}"\n'
        'if [ -z "$CODEX_BIN" ]; then\n'
        '  CODEX_BIN="$(command -v codex || true)"\n'
        "fi\n"
        'if [ -z "$CODEX_BIN" ]; then\n'
        '  CODEX_BIN="$HOME/.local/bin/codex"\n'
        "fi\n"
        'exec "$CODEX_BIN" \\\n'
        f"{override_lines}"
        '  "$@"\n'
    )
    CODEX_SHIM_PROFILE_CLI_PATH.chmod(0o755)

    CODEX_SHIM_DESKTOP_WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_SHIM_DESKTOP_WRAPPER_PATH.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "export BAMF_DESKTOP_FILE_HINT=\"${BAMF_DESKTOP_FILE_HINT:-/usr/share/applications/codex-desktop.desktop}\"\n"
        "export CHROME_DESKTOP=\"${CHROME_DESKTOP:-codex-desktop.desktop}\"\n"
        f"export CODEX_CLI_PATH={shlex.quote(str(CODEX_SHIM_PROFILE_CLI_PATH))}\n"
        "export CODEX_CHROME_EXECUTABLE=\"${CODEX_CHROME_EXECUTABLE:-/usr/bin/brave-origin-nightly}\"\n"
        "BRAVE_CONFIG_DIR=\"${XDG_CONFIG_HOME:-$HOME/.config}/BraveSoftware/Brave-Origin-Nightly\"\n"
        "export CODEX_CHROME_USER_DATA_DIR=\"${CODEX_CHROME_USER_DATA_DIR:-$BRAVE_CONFIG_DIR}\"\n"
        "export CODEX_CHROME_PREFERENCES_PATH=\"${CODEX_CHROME_PREFERENCES_PATH:-$BRAVE_CONFIG_DIR/Default/Preferences}\"\n"
        "export CODEX_CHROME_NATIVE_HOST_MANIFEST_PATH=\"${CODEX_CHROME_NATIVE_HOST_MANIFEST_PATH:-$BRAVE_CONFIG_DIR/NativeMessagingHosts/com.openai.codexextension.json}\"\n"
        "export BROWSER=\"${BROWSER:-/usr/bin/brave-origin-nightly}\"\n"
        "export NO_PROXY=127.0.0.1,localhost,::1\n"
        "export no_proxy=127.0.0.1,localhost,::1\n\n"
        f"CODEX_DESKTOP_APP_DIR=\"${{CODEX_SHIM_DESKTOP_APP_DIR:-${{CODEX_DESKTOP_APP_DIR:-{LINUX_SYSTEM_CODEX_APP}}}}}\"\n"
        'SETSID_BIN="$(command -v setsid || true)"\n'
        'if [ -n "$SETSID_BIN" ]; then\n'
        '  exec "$SETSID_BIN" -f "$CODEX_DESKTOP_APP_DIR/start.sh" --x11 "$@"\n'
        "fi\n"
        'exec "$CODEX_DESKTOP_APP_DIR/start.sh" --x11 "$@"\n'
    )
    CODEX_SHIM_DESKTOP_WRAPPER_PATH.chmod(0o755)


def _profile_wrapper_values(
    model_slug: str | None = None,
    provider_name: str | None = None,
    port: int | None = None,
) -> tuple[str, str, int]:
    if model_slug and provider_name and port:
        return model_slug, provider_name, port
    parsed_model = model_slug
    parsed_provider = provider_name
    parsed_port = port or DEFAULT_PORT
    if CODEX_SHIM_PROFILE_PATH.exists():
        for line in CODEX_SHIM_PROFILE_PATH.read_text().splitlines():
            stripped = line.strip()
            if parsed_model is None and stripped.startswith("model = "):
                parsed_model = _toml_unquote(stripped.split("=", 1)[1].strip())
            elif parsed_provider is None and stripped.startswith("name = "):
                parsed_provider = _toml_unquote(stripped.split("=", 1)[1].strip())
            elif stripped.startswith("base_url = "):
                value = _toml_unquote(stripped.split("=", 1)[1].strip())
                prefix = "http://127.0.0.1:"
                suffix = "/v1"
                if value.startswith(prefix) and value.endswith(suffix):
                    try:
                        parsed_port = int(value[len(prefix) : -len(suffix)])
                    except ValueError:
                        pass
    return parsed_model or "opencode-go-deepseek-v4-pro", parsed_provider or "Codex Shim", parsed_port


def _toml_unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _quit_linux_codex_desktop() -> None:
    try:
        subprocess.run(
            ["pkill", "-TERM", "-f", "codex-desktop"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.0)
    except OSError:
        pass


def patch_codex_app() -> int:
    if sys.platform.startswith("linux"):
        return _patch_linux_codex_app()
    print("patch-app supports Linux Codex Desktop overlays only.", file=sys.stderr)
    return 1


def restore_codex_app_bundle() -> int:
    if sys.platform.startswith("linux"):
        return _restore_linux_codex_app_bundle()
    print("restore-app supports Linux Codex Desktop overlays only.", file=sys.stderr)
    return 1


def _patch_linux_codex_app() -> int:
    source_app = Path(os.environ.get("CODEX_DESKTOP_LINUX_SOURCE_DIR", str(LINUX_SYSTEM_CODEX_APP)))
    target_app = Path(os.environ.get("CODEX_DESKTOP_LINUX_PATCHED_DIR", str(LINUX_USER_CODEX_APP)))
    source_asar = source_app / "resources" / "app.asar"
    target_asar = target_app / "resources" / "app.asar"
    if not source_asar.exists():
        print(f"Codex Desktop Linux app.asar not found at {source_asar}.", file=sys.stderr)
        return 1
    if not _has_command("npx"):
        print("npx is required to patch the Electron asar bundle.", file=sys.stderr)
        return 1

    source_hash = _app_asar_hash(source_asar)
    stamp = target_app / LINUX_SOURCE_HASH_STAMP
    stamp_hash = stamp.read_text().strip() if stamp.exists() else ""
    if not target_asar.exists() or stamp_hash != source_hash:
        if target_app.exists():
            shutil.rmtree(target_app)
        target_app.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_app, target_app, symlinks=True)
        stamp.write_text(source_hash + "\n")
        print(f"Copied Codex Desktop Linux app from {source_app} to {target_app}.")

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    backup = RUNTIME_DIR / "linux-app.asar.before-codex-shim-model-picker-patch"
    if not backup.exists():
        backup.write_bytes(target_asar.read_bytes())
        print(f"Backed up original Linux app.asar to {backup}.")
    versioned_backup = RUNTIME_DIR / f"linux-app.asar.before-codex-shim-model-picker-patch.{_app_asar_hash(target_asar)[:12]}"
    if not versioned_backup.exists():
        versioned_backup.write_bytes(target_asar.read_bytes())
        print(f"Backed up current Linux app.asar to {versioned_backup}.")

    workdir = RUNTIME_DIR / "app-asar-work-linux"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    subprocess.run(["npx", "--yes", "asar", "extract", str(target_asar), str(workdir)], check=True)
    changed = _patch_codex_desktop_bundles(workdir)
    if changed is None:
        return 1
    if changed:
        subprocess.run(["npx", "--yes", "asar", "pack", str(workdir), str(target_asar)], check=True)
        print(f"Packed patched Linux app.asar at {target_asar}.")

    content_dir = target_app / "content"
    if content_dir.exists():
        content_changed = _patch_codex_desktop_bundles(content_dir)
        if content_changed is None:
            return 1
        if content_changed:
            print(f"Patched Linux webview assets under {content_dir}.")
        else:
            print("Linux webview asset patches are already applied.")
    print(f"Patched Linux Codex Desktop copy: {target_app}")
    return 0


def _restore_linux_codex_app_bundle() -> int:
    target_app = Path(os.environ.get("CODEX_DESKTOP_LINUX_PATCHED_DIR", str(LINUX_USER_CODEX_APP)))
    target_asar = target_app / "resources" / "app.asar"
    backup = RUNTIME_DIR / "linux-app.asar.before-codex-shim-model-picker-patch"
    if not backup.exists():
        print(f"No Linux app.asar backup found at {backup}.")
        return 0
    if not target_asar.exists():
        print(f"No patched Linux app.asar found at {target_asar}.")
        return 0
    target_asar.write_bytes(backup.read_bytes())
    print(f"Restored {target_asar} from {backup}.")
    return 0


def _has_command(command: str) -> bool:
    from shutil import which

    return which(command) is not None


def _app_asar_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _patch_codex_desktop_bundles(workdir: Path) -> bool | None:
    patches = [
        (
            "model picker allowlist filter",
            MODEL_PICKER_PATCH_VARIANTS,
        ),
        (
            "shim-mode sidebar provider filter",
            SIDEBAR_RECENT_THREADS_PATCH_VARIANTS,
        ),
    ]
    changed = False
    for label, variants in patches:
        result = _patch_first_matching_variant(workdir, label, variants)
        if result is None:
            return None
        if result:
            changed = True
            print(f"Patched Codex Desktop {label}.")
        else:
            print(f"Codex Desktop {label} patch is already applied.")
    return changed


def _patch_first_matching_variant(
    workdir: Path,
    label: str,
    variants: list[tuple[list[str], str, str]],
) -> bool | None:
    for globs, needle, replacement in variants:
        bundle_file = _find_js_bundle(workdir, globs, needle, replacement)
        if bundle_file is None:
            continue
        result = _replace_once(bundle_file, needle, replacement)
        if result is None:
            print(f"Could not patch the expected {label} in Codex Desktop.", file=sys.stderr)
            return None
        return result
    print(f"Could not find the expected {label} in Codex Desktop.", file=sys.stderr)
    return None


def _find_js_bundle(workdir: Path, globs: list[str], needle: str, replacement: str) -> Path | None:
    assets_dir = workdir / "webview" / "assets"
    if not assets_dir.exists():
        return None
    candidates: list[Path] = []
    for pattern in globs:
        candidates.extend(p for p in sorted(assets_dir.glob(pattern)) if p not in candidates)
    for path in candidates:
        text = _read_text_lossy(path)
        if needle in text or replacement in text:
            return path
    return None


def _replace_once(path: Path, needle: str, replacement: str) -> bool | None:
    text = _read_text_lossy(path)
    if replacement in text:
        return False
    count = text.count(needle)
    if count != 1:
        return None
    path.write_text(text.replace(needle, replacement, 1))
    return True


def _read_text_lossy(path: Path) -> str:
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return path.read_text(errors="ignore")


def _provider_display_name(models, slug: str, router_config=None) -> str:
    if router_config is not None and slug == router_config.slug:
        return router_config.display_name
    if chatgpt_passthrough_available():
        display_name = chatgpt_passthrough_display_names().get(slug)
        if display_name:
            return display_name
    if cursor_passthrough_available():
        display_name = cursor_passthrough_display_names().get(slug)
        if display_name:
            return display_name
    for model in models:
        if model.slug == slug:
            route = str(model.raw.get("provider_display_name") or "").strip()
            return f"{route} / {model.display_name}" if route else model.display_name
    return "Codex Shim"


def _managed_config_blocks(
    default_slug: str,
    port: int,
    previous_top_level: dict[str, str] | None = None,
    provider_name: str = "Codex Shim",
) -> tuple[str, str]:
    metadata = ""
    if previous_top_level:
        metadata = PREVIOUS_TOP_LEVEL_PREFIX + json.dumps(previous_top_level, sort_keys=True) + "\n"
    top_block = f'''{MANAGED_BEGIN}
{metadata}model = "{_toml_escape(default_slug)}"
model_provider = "{PROVIDER_NAME}"
model_catalog_json = "{_toml_escape(str(CATALOG_PATH))}"
{MANAGED_END}
'''

    provider_block = f'''{MANAGED_BEGIN}
[model_providers.{PROVIDER_NAME}]
name = "{_toml_escape(provider_name)}"
base_url = "http://127.0.0.1:{port}/v1"
wire_api = "responses"
experimental_bearer_token = "dummy"
request_max_retries = 3
stream_max_retries = 3
stream_idle_timeout_ms = 600000
{MANAGED_END}
'''
    return top_block, provider_block


def _remove_managed_config(text: str) -> str:
    while MANAGED_BEGIN in text:
        before, rest = text.split(MANAGED_BEGIN, 1)
        if MANAGED_END not in rest:
            return before
        _, after = rest.split(MANAGED_END, 1)
        text = before + after
    return text


def _remove_top_level_keys(text: str, keys: set[str]) -> str:
    lines = text.splitlines()
    output: list[str] = []
    in_top_level = True
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_top_level = False
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if in_top_level and key in keys:
            continue
        output.append(line)
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def _extract_top_level_key_lines(text: str, keys: set[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    in_top_level = True
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_top_level = False
        if not in_top_level or not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in keys:
            found[key] = line
    return found


def _managed_previous_top_level(text: str) -> dict[str, str]:
    in_managed = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == MANAGED_BEGIN:
            in_managed = True
            continue
        if stripped == MANAGED_END:
            in_managed = False
            continue
        if in_managed and stripped.startswith(PREVIOUS_TOP_LEVEL_PREFIX):
            encoded = stripped[len(PREVIOUS_TOP_LEVEL_PREFIX) :]
            try:
                payload = json.loads(encoded)
            except json.JSONDecodeError:
                return {}
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items() if k in MANAGED_TOP_LEVEL_KEYS}
    return {}


def _restore_missing_top_level_keys(text: str, previous_top_level: dict[str, str]) -> str:
    if not previous_top_level:
        return text
    current = _extract_top_level_key_lines(text, MANAGED_TOP_LEVEL_KEYS)
    lines = [
        previous_top_level[key]
        for key in ("model", "model_provider", "model_catalog_json")
        if key in previous_top_level and key not in current
    ]
    if not lines:
        return text
    prefix = "\n".join(lines) + "\n"
    if text and not text.startswith("\n"):
        return prefix + text
    return prefix + text.lstrip()


def _remove_section(text: str, section: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    skipping = False
    header = f"[{section}]"
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped == header
            if skipping:
                continue
        if not skipping:
            output.append(line)
    return "\n".join(output) + ("\n" if text.endswith("\n") else "")


def _popen_daemon(cmd: list[str], log, env: dict[str, str]) -> subprocess.Popen:
    kwargs = {"cwd": str(RUNTIME_DIR), "env": env, "stdout": log, "stderr": log}
    return subprocess.Popen(cmd, start_new_session=True, **kwargs)


def _terminate_pid(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)


def _override_args(settings_path: Path, port: int) -> list[str]:
    models = _load_models(settings_path)
    try:
        default_slug = default_model_slug(models)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    pairs = codex_config_overrides(CATALOG_PATH, default_slug, port)
    args: list[str] = []
    for pair in pairs:
        args.extend(["-c", pair])
    return args


def _resolve_model_slug(models, requested: str | None, router_config=None) -> str:
    if requested is None:
        current = _current_managed_model()
        if current in _valid_model_slugs(models, router_config):
            return current
        try:
            return default_model_slug(models)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if router_config is not None and requested == router_config.slug:
        return requested
    if is_chatgpt_passthrough_slug(requested):
        if not chatgpt_passthrough_available():
            raise SystemExit(
                "ChatGPT passthrough requires a Codex login. "
                "Run `codex login` so ~/.codex/auth.json contains tokens.access_token."
            )
        if requested.startswith("openai-gpt-"):
            return CHATGPT_MODEL_SLUG
        return requested
    if is_cursor_passthrough_slug(requested):
        if not cursor_passthrough_available():
            raise SystemExit(
                "Composer passthrough requires Cursor CLI login. "
                "Run `cursor-agent login`, then `cursor-agent status`."
            )
        return requested if requested in cursor_passthrough_display_names() else "composer-2-5"
    by_slug = {model.slug: model.slug for model in models}
    by_model: dict[str, list[str]] = {}
    for model in models:
        by_model.setdefault(model.model, []).append(model.slug)
    if requested in by_slug:
        return requested
    configured = {model.slug: model for model in models}
    if requested in configured and not byok_model_has_credentials(configured[requested]):
        if is_cursor_passthrough_slug(requested):
            raise SystemExit(
                f"Model {requested!r} is configured for custom routing but has no API key. "
                "Remove it from ~/.codex-shim/models.json to use Cursor subscription passthrough, "
                "or set CURSOR_API_KEY / ~/.codex-shim/cursor-api-key."
            )
        raise SystemExit(
            f"Model {requested!r} is configured but has no API key. "
            "Set the route API key in ~/.codex-shim/models.json or the matching env var."
        )
    if requested in by_model and len(by_model[requested]) == 1:
        return by_model[requested][0]
    matches = [model.slug for model in models if requested.lower() in model.display_name.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise SystemExit(f"Ambiguous model {requested!r}. Matches: {', '.join(matches)}")
    raise SystemExit(f"Unknown shim model {requested!r}. Run: codex-shim model list")


def _current_managed_model() -> str | None:
    if not CODEX_SHIM_PROFILE_PATH.exists():
        return None
    in_managed = False
    for line in CODEX_SHIM_PROFILE_PATH.read_text().splitlines():
        stripped = line.strip()
        if stripped == MANAGED_BEGIN:
            in_managed = True
            continue
        if stripped == MANAGED_END:
            in_managed = False
            continue
        if in_managed and stripped.startswith("model = "):
            return stripped.split("=", 1)[1].strip().strip('"')
    return None


def _valid_model_slugs(models, router_config=None) -> set[str]:
    slugs = {model.slug for model in usable_byok_models(models)}
    if router_config is not None:
        slugs.add(router_config.slug)
    if chatgpt_passthrough_available():
        slugs.update(chatgpt_passthrough_slugs())
    if cursor_passthrough_available():
        slugs.update(cursor_passthrough_display_names())
    return slugs


def _healthy(port: int) -> bool:
    return _health(port) is not None


def _health(port: int) -> dict | None:
    try:
        with urlopen(
            f"http://{DEFAULT_HOST}:{port}/health",
            timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        ) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text().strip())
    except Exception:
        return None


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _entrypoint() -> int:
    try:
        return main()
    except BrokenPipeError:
        # Downstream pipe (e.g. `codex-shim list | head`) closed early. Mute the
        # interpreter's atexit flush so we exit cleanly instead of dumping a
        # traceback to stderr.
        try:
            sys.stdout.flush()
        except BrokenPipeError:
            pass
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
