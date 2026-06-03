# Linux desktop provider bridge (fork maintenance)

This document describes the **`rabesss/codex-shim`** branch that extends upstream
[0xSero/codex-shim](https://github.com/0xSero/codex-shim) for **Codex Desktop on
Linux** with a multi-provider BYOK catalog. It is written for maintainers, not as
a personal workstation runbook.

## What this fork adds

| Area | Behavior |
|------|----------|
| **Model matrix** | `codex-shim desktop write-models` writes `~/.codex-shim/models.json` with provider-prefixed slugs (`opencode-go-*`, `zai-*`, `commandcode-*`, `grok-*`, …). |
| **Credentials** | Matrix rows use `api_key_credential` names only; decrypt at runtime via systemd `LoadCredentialEncrypted=` (or env/file fallbacks documented in README). |
| **Routing** | Direct API-key providers hit their real `base_url`. `commandcode-*` uses local CommandCode adapter (`127.0.0.1:8318`). `grok-*` uses CLIProxyAPI (`127.0.0.1:8317`) for OAuth-backed xAI CLI. |
| **Desktop picker** | `codex-shim patch-app` / `restore-app` patch the Linux overlay under `~/.local/share/codex-desktop-linux-overlay/patched-app` (copy of `/opt/codex-desktop`), same allowlist idea as macOS. |
| **Catalog limits** | Per-model `max_context_limit`, `auto_compact_token_limit`, `truncation_limit`, and `no_image_support` are set from live smoke tests where possible. |

Upstream remains the source of truth for Responses translation, Auto Router, ChatGPT
passthrough, and core CLI behavior. Rebase this branch onto `origin/main` regularly.

## Quick maintainer workflow

```bash
git fetch origin
git rebase origin/main   # resolve conflicts in cli.py / patch-app if any

python3 -m pip install -e ".[dev]"  # or pytest + aiohttp as in README
python3 -m pytest tests/ -q

codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
systemctl --user restart codex-shim.service   # if you use the user unit
codex-shim status
```

Adjust `desktop_models.py` when adding providers or changing capability flags, then
regenerate models and rerun tests (`test_desktop_model_matrix_*`).

## Syncing with upstream

1. **Fetch** `origin` (0xSero) and merge or rebase your branch.
2. **Re-run** the full pytest suite; fork-specific tests live in `tests/test_settings_catalog.py` and Linux patch tests if present.
3. **Re-smoke** one model per route class: direct BYOK, CommandCode slug, CPA Grok slug, plus one vision-capable row if you changed `no_image_support`.
4. **Regenerate** `models.json` on any machine that deploys from this branch; do not commit secrets into the repo.

## CLI surface

| Command | Purpose |
|---------|---------|
| `codex-shim desktop write-models` | Write bundled matrix to `--output` (default `~/.codex-shim/models.json`). |
| `codex-shim desktop write-models --no-commandcode` | Omit `commandcode-*` rows (adapter not running). |
| `codex-shim desktop write-models --no-cpa-oauth` | Omit `grok-*` rows (CPA not running). |

The hidden `codex-shim ravish write-models` alias exists for one release cycle of
backward compatibility; prefer `desktop write-models` in scripts and docs.

## systemd credentials (example)

The service unit should map encrypted credential names to the names used in
`models.json`, for example:

- `DROID_BYOK_ZAI_CODING_API_KEY`
- `DROID_BYOK_MINIMAX_API_KEY`
- `DROID_BYOK_OPENCODE_GO_API_KEY`
- `XIAOMI_MIMO_TOKEN_PLAN_API_KEY`
- `CROFAI_API_KEY`
- `CLIPROXY_INTERNAL_API_KEY`

CommandCode adapter routes use `api_key: "dummy"` because auth is handled by the
local adapter, not the shim.

## Capability policy

- Treat **Xiaomi Token Plan** as text-only unless upstream starts accepting image
  payloads on your endpoint.
- Set **`no_image_support: false`** only after a live 1×1 PNG request succeeds
  through `codex-shim` to that slug.
- Prefer explicit context limits over a single global 128k default so Desktop
  compaction behavior matches each provider.

## Publishing

- **Remote:** `https://github.com/rabesss/codex-shim`
- **Suggested branch name:** `linux/desktop-provider-bridge` (rename from older
  branch names when convenient).
- **Force-push** only after rewriting history locally; coordinate if others clone
  the fork branch.

## Related reading

- Root [README.md](../README.md) — install, routing diagram, security.
- Upstream issues/PRs for Codex Desktop version bumps affecting `patch-app` needles.