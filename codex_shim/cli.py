from __future__ import annotations

import argparse
import os
from pathlib import Path
import ctypes
import signal
import subprocess
import sys
import time
import hashlib
import json
import plistlib
import shutil
import struct
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
from .desktop_models import write_desktop_models


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / ".codex-shim"
CATALOG_PATH = RUNTIME_DIR / "custom_model_catalog.json"
CONFIG_PATH = RUNTIME_DIR / "config.toml"
PID_PATH = RUNTIME_DIR / "shim.pid"
LOG_PATH = RUNTIME_DIR / "shim.log"
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
CODEX_CONFIG_BACKUP_PATH = RUNTIME_DIR / "config.toml.before-codex-shim"
MANAGED_BEGIN = "# >>> codex-shim managed >>>"
MANAGED_END = "# <<< codex-shim managed <<<"
WINDOWS_PROCESS_TERMINATE = 0x0001
WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WINDOWS_STILL_ACTIVE = 259
PREVIOUS_TOP_LEVEL_PREFIX = "# codex-shim previous-top-level = "
MANAGED_TOP_LEVEL_KEYS = {"model", "model_provider", "model_catalog_json"}
HEALTH_CHECK_TIMEOUT_SECONDS = 3.0
APP_ASAR_BACKUP_NAME = "app.asar.before-codex-shim-model-picker-patch"
INFO_PLIST_BACKUP_NAME = "Info.plist.before-codex-shim-model-picker-patch"
SYSTEM_CODEX_APP = Path("/Applications/Codex.app")
USER_CODEX_APP = Path.home() / "Applications" / "Codex.app"
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
    sub.add_parser("patch-app", help="Patch Codex Desktop picker/sidebar handling for custom shim models.")
    sub.add_parser("restore-app", help="Restore Codex Desktop app.asar from the pre-patch backup.")

    model_parser = sub.add_parser("model", help="List or set the active shim model in Codex config.")
    model_sub = model_parser.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("list")
    use_parser = model_sub.add_parser("use")
    use_parser.add_argument("model_slug")

    codex_parser = sub.add_parser("codex", help="Run Codex CLI with opt-in shim config overrides.")
    codex_parser.add_argument("args", nargs=argparse.REMAINDER)

    app_parser = sub.add_parser("app", help="Launch Codex Desktop with opt-in shim config overrides.")
    app_parser.add_argument("-m", "--model", dest="model_slug")
    app_parser.add_argument("path", nargs="?", default=".")

    desktop_parser = sub.add_parser("desktop", help="Linux Codex Desktop model matrix helpers.")
    desktop_sub = desktop_parser.add_subparsers(dest="desktop_command", required=True)
    desktop_write = desktop_sub.add_parser("write-models", help="Write provider-prefixed models.json for Desktop.")
    desktop_write.add_argument("--output", type=Path, default=DEFAULT_SETTINGS)
    desktop_write.add_argument("--no-commandcode", action="store_true", help="Omit direct CommandCode adapter routes.")
    desktop_write.add_argument("--no-cpa-oauth", action="store_true", help="Omit CPA-backed OAuth-only routes such as Grok CLI.")
    # Deprecated alias: `codex-shim ravish write-models` (hidden from help)
    ravish_parser = sub.add_parser("ravish", help=argparse.SUPPRESS)
    ravish_sub = ravish_parser.add_subparsers(dest="ravish_command", required=True)
    ravish_write = ravish_sub.add_parser("write-models", help=argparse.SUPPRESS)
    ravish_write.add_argument("--output", type=Path, default=DEFAULT_SETTINGS)
    ravish_write.add_argument("--no-commandcode", action="store_true")
    ravish_write.add_argument("--no-cpa-oauth", action="store_true")

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
            install_codex_config(args.settings, args.port)
        return code
    if args.command in {"stop", "disable"}:
        if args.command == "disable":
            restore_codex_config()
        return stop()
    if args.command == "restart":
        stop()
        generate(args.settings, args.port)
        return start(args.settings, args.port)
    if args.command == "status":
        return status(args.port)
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
            install_codex_config(args.settings, args.port, args.model_slug)
            print(f"Active Codex shim model: {args.model_slug}")
            return 0
    if args.command == "codex":
        generate(args.settings, args.port)
        ensure_started(args.settings, args.port)
        exec_codex(args.settings, args.port, args.args)
        return 0
    if args.command == "app":
        generate(args.settings, args.port)
        ensure_started(args.settings, args.port)
        install_codex_config(args.settings, args.port, args.model_slug)
        exec_codex_app(args.settings, args.port, args.path)
        return 0
    if args.command in {"desktop", "ravish"}:
        write_cmd = getattr(args, "desktop_command", None) or getattr(args, "ravish_command", None)
        if write_cmd == "write-models":
            output = write_desktop_models(
                args.output,
                include_commandcode=not args.no_commandcode,
                include_cpa_oauth=not args.no_cpa_oauth,
            )
            print(f"Wrote desktop model matrix to {output}")
            return 0
    return 2


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
    if os.name == "nt":
        raise SystemExit(subprocess.call(args, env=env))
    os.execvpe("codex", args, env)


def exec_codex_app(settings_path: Path, port: int, path: str) -> None:
    _quit_codex_app()
    codex_app = patched_codex_app_bundle()
    if codex_app is not None:
        subprocess.Popen(["open", "-a", str(codex_app)], env=_with_loopback_no_proxy(os.environ.copy()))
    else:
        args = ["codex", "app", path]
        subprocess.Popen(args, env=_with_loopback_no_proxy(os.environ.copy()))
    _foreground_codex_app()


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


def _quit_codex_app() -> None:
    script = 'tell application "Codex" to if it is running then quit'
    try:
        subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
    except OSError:
        pass


def patch_codex_app() -> int:
    if sys.platform == "darwin":
        return _patch_macos_codex_app()
    if sys.platform.startswith("linux"):
        return _patch_linux_codex_app()
    print("patch-app supports macOS app bundles and this local Linux Codex Desktop overlay only.", file=sys.stderr)
    return 1


def _patch_macos_codex_app() -> int:
    codex_app = _codex_app_bundle_for_patch()
    app_asar = codex_app / "Contents/Resources/app.asar"
    info_plist = codex_app / "Contents/Info.plist"
    backup = RUNTIME_DIR / APP_ASAR_BACKUP_NAME
    info_backup = RUNTIME_DIR / INFO_PLIST_BACKUP_NAME

    if not app_asar.exists():
        print(f"Codex app bundle not found at {codex_app}.", file=sys.stderr)
        return 1
    if codex_app == USER_CODEX_APP:
        print(f"Patching user Codex copy at {codex_app}.")
    if not info_plist.exists():
        print(f"Codex Info.plist not found at {info_plist}.", file=sys.stderr)
        return 1
    if not _has_command("npx"):
        print("npx is required to patch the Electron asar bundle.", file=sys.stderr)
        return 1

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(app_asar.read_bytes())
        print(f"Backed up original app.asar to {backup}.")
    versioned_backup = RUNTIME_DIR / f"app.asar.before-codex-shim-model-picker-patch.{_app_asar_hash(app_asar)[:12]}"
    if not versioned_backup.exists():
        versioned_backup.write_bytes(app_asar.read_bytes())
        print(f"Backed up current app.asar to {versioned_backup}.")
    if not info_backup.exists():
        info_backup.write_bytes(info_plist.read_bytes())
        print(f"Backed up original Info.plist to {info_backup}.")

    _quit_codex_app()
    workdir = RUNTIME_DIR / "app-asar-work-user"
    if workdir.exists():
        import shutil

        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    subprocess.run(["npx", "--yes", "asar", "extract", str(app_asar), str(workdir)], check=True)
    changed = _patch_codex_desktop_bundles(workdir)
    if changed is None:
        return 1
    if changed:
        subprocess.run(["npx", "--yes", "asar", "pack", str(workdir), str(app_asar)], check=True)
        _update_app_asar_integrity(app_asar, info_plist)
        _resign_codex_app(codex_app)
    return 0


def restore_codex_app_bundle() -> int:
    if sys.platform.startswith("linux"):
        return _restore_linux_codex_app_bundle()
    if sys.platform != "darwin":
        print("restore-app supports macOS app bundles and this local Linux Codex Desktop overlay only.", file=sys.stderr)
        return 1
    codex_app = patched_codex_app_bundle() or _codex_app_bundle_for_patch()
    app_asar = codex_app / "Contents/Resources/app.asar"
    info_plist = codex_app / "Contents/Info.plist"
    backup = RUNTIME_DIR / APP_ASAR_BACKUP_NAME
    info_backup = RUNTIME_DIR / INFO_PLIST_BACKUP_NAME
    if not backup.exists():
        print(f"No app.asar backup found at {backup}.")
        return 0
    _quit_codex_app()
    app_asar.write_bytes(backup.read_bytes())
    if info_backup.exists():
        info_plist.write_bytes(info_backup.read_bytes())
        print(f"Restored {info_plist} from {info_backup}.")
    elif info_plist.exists():
        _update_app_asar_integrity(app_asar, info_plist)
    _resign_codex_app(codex_app)
    print(f"Restored {app_asar} from {backup}.")
    return 0


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


def _app_asar_header_hash(path: Path) -> str:
    with path.open("rb") as f:
        _, _, _, json_size = struct.unpack("<4I", f.read(16))
        header_json = f.read(json_size)
    return hashlib.sha256(header_json).hexdigest()


def _update_app_asar_integrity(app_asar: Path, info_plist: Path) -> None:
    header_hash = _app_asar_header_hash(app_asar)
    data = plistlib.loads(info_plist.read_bytes())
    try:
        data["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] = header_hash
    except KeyError as exc:
        raise RuntimeError(f"Could not update ElectronAsarIntegrity in {info_plist}") from exc
    info_plist.write_bytes(plistlib.dumps(data))
    print("Updated ElectronAsarIntegrity for app.asar.")


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


def patched_codex_app_bundle() -> Path | None:
    for codex_app in (USER_CODEX_APP, SYSTEM_CODEX_APP):
        app_asar = codex_app / "Contents/Resources/app.asar"
        if app_asar.exists() and _app_asar_is_patched(app_asar):
            return codex_app
    return None


def _codex_app_bundle_for_patch() -> Path:
    system_asar = SYSTEM_CODEX_APP / "Contents/Resources/app.asar"
    if system_asar.exists() and _path_is_writable(system_asar):
        return SYSTEM_CODEX_APP
    return _ensure_user_codex_app()


def _ensure_user_codex_app() -> Path:
    user_asar = USER_CODEX_APP / "Contents/Resources/app.asar"
    if user_asar.exists():
        return USER_CODEX_APP
    system_asar = SYSTEM_CODEX_APP / "Contents/Resources/app.asar"
    if not system_asar.exists():
        raise SystemExit(f"Codex Desktop not found at {SYSTEM_CODEX_APP}.")
    USER_CODEX_APP.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ditto", str(SYSTEM_CODEX_APP), str(USER_CODEX_APP)], check=True)
    print(f"Copied Codex Desktop to {USER_CODEX_APP} for patching.")
    return USER_CODEX_APP


def _path_is_writable(path: Path) -> bool:
    try:
        with path.open("r+b"):
            return True
    except OSError:
        return False


def _app_asar_is_patched(app_asar: Path) -> bool:
    try:
        text = app_asar.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return False
    return any(replacement in text for replacement in MODEL_PICKER_REPLACEMENTS) and any(
        replacement in text for replacement in SIDEBAR_RECENT_THREADS_REPLACEMENTS
    )


def _resign_codex_app(codex_app: Path = SYSTEM_CODEX_APP) -> None:
    # Electron validates app.asar through the bundle signature metadata at
    # startup. Re-sign after patching so the modified archive does not trip the
    # asar integrity check.
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(codex_app)],
        check=True,
    )
    print(f"Re-signed {codex_app} after patch.")


def _foreground_codex_app() -> None:
    script = '''
tell application "Codex" to activate
delay 0.5
tell application "System Events"
  if exists process "Codex" then
    tell process "Codex"
      set frontmost to true
      if (count of windows) is 0 then
        keystroke "n" using command down
        delay 0.3
      end if
      if (count of windows) > 0 then
        set position of window 1 to {80, 60}
        set size of window 1 to {1400, 980}
      end if
    end tell
  end if
end tell
'''
    try:
        subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


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
            return model.display_name
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
    kwargs = {"cwd": str(PROJECT_ROOT), "env": env, "stdout": log, "stderr": log}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        return subprocess.Popen(cmd, creationflags=creationflags, **kwargs)
    return subprocess.Popen(cmd, start_new_session=True, **kwargs)


def _terminate_pid(pid: int) -> None:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(WINDOWS_PROCESS_TERMINATE, False, pid)
        if handle:
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, 0)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return
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
                f"Model {requested!r} is configured for BYOK but has no API key. "
                "Remove it from ~/.codex-shim/models.json to use Cursor subscription passthrough, "
                "or set CURSOR_API_KEY / ~/.codex-shim/cursor-api-key."
            )
        raise SystemExit(
            f"Model {requested!r} is configured but has no API key. "
            "Set the provider API key in ~/.codex-shim/models.json or the matching env var."
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
    if not CODEX_CONFIG_PATH.exists():
        return None
    in_managed = False
    for line in CODEX_CONFIG_PATH.read_text().splitlines():
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
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == WINDOWS_STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
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
