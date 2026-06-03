# Fork maintenance: Linux desktop provider bridge

Maintainer notes for **[rabesss/codex-shim](https://github.com/rabesss/codex-shim)** on branch
**`linux/desktop-provider-bridge`**, rebased onto upstream
**[0xSero/codex-shim](https://github.com/0xSero/codex-shim)** (`origin/main`).

End-user setup: [`linux-desktop.md`](linux-desktop.md). Upstream install and core
commands: [README](../README.md).

## Fork delta vs `origin/main`

Compare at any time:

```bash
git fetch origin
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- ':!*.md' ':!docs/*'
```

**Code and tests** (as of branch tip ~`943f434`):

| File | Change |
|------|--------|
| `codex_shim/desktop_models.py` | **New.** Bundled `models.json` matrix (`desktop_models_payload`, `write_desktop_models`). |
| `codex_shim/cli.py` | `desktop write-models`; hidden deprecated `ravish write-models`; Linux `patch-app` / `restore-app`; multi-variant Desktop JS needles; health check timeout 3s. |
| `codex_shim/settings.py` | `api_key_env`, `api_key_credential`, `api_key_file`; `$CREDENTIALS_DIRECTORY` + env fallback; `auto_compact_token_limit`, `truncation_limit`; no silent Cursor key fallback on empty `api_key`. |
| `codex_shim/catalog.py` | Provider suffix on `display_name`; `provider_display_name` from settings; CommandCode/CLIProxyAPI labels from `base_url`; reasoning summary defaults. |
| `codex_shim/server.py` | Credential error text; versioned `/vN` base URL join. |
| `tests/test_settings_catalog.py` | Desktop matrix, credentials, catalog labels, Linux bundle patch tests. |
| `tests/test_server.py` | Minor server test adjustment. |

**Documentation only on the branch:** `README.md` (upstream-aligned + short fork pointer),
`docs/FORK.md`, and user guide `docs/linux-desktop.md`.

No other markdown files were changed in the fork diff.

## Behavioral summary

| Area | Behavior |
|------|----------|
| **Model matrix** | `codex-shim desktop write-models` → `~/.codex-shim/models.json` (or `--output`) with prefixed slugs and `generated_by: codex-shim-desktop-matrix`. |
| **Credentials** | Rows use `api_key_credential` names; CommandCode rows use `api_key: "dummy"`. |
| **Routing** | Direct providers → real `base_url`. `commandcode-*` → `127.0.0.1:8318`. `grok-*` → `127.0.0.1:8317` + `CLIPROXY_INTERNAL_API_KEY`. |
| **Desktop picker** | `patch-app` / `restore-app` on macOS bundle or Linux overlay under `~/.local/share/codex-desktop-linux-overlay/patched-app`. |
| **Catalog** | Picker labels gain ` - Provider` suffix; per-model compaction/truncation limits flow from settings into catalog entries. |

### Matrix provider families (`desktop_models.py`)

| Family | Slug examples | Credential / auth |
|--------|---------------|-------------------|
| Z.ai Coding | `zai-glm-5-1`, `zai-glm-5`, … | `DROID_BYOK_ZAI_CODING_API_KEY` |
| MiniMax Coding | `minimax-m2-7`, … | `DROID_BYOK_MINIMAX_API_KEY` |
| OpenCode Go | `opencode-go-*` | `DROID_BYOK_OPENCODE_GO_API_KEY` |
| OpenCode Zen | `opencode-zen-*` | same OpenCode Go credential |
| Xiaomi Token Plan | `xiaomi-mimo-*` | `XIAOMI_MIMO_TOKEN_PLAN_API_KEY` |
| CrofAI | `crof-*` | `CROFAI_API_KEY` |
| CommandCode | `commandcode-*` | `api_key: "dummy"` (adapter auth) |
| CLIProxyAPI / Grok | `grok-*` | `CLIPROXY_INTERNAL_API_KEY` |

Optional matrix sections: `--no-commandcode`, `--no-cpa-oauth`.

### Deprecated CLI alias

`codex-shim ravish write-models` is hidden (`argparse.SUPPRESS`) for one release
cycle of backward compatibility. Scripts and docs should use
`codex-shim desktop write-models` only.

## CLI surface (fork-specific)

| Command | Purpose |
|---------|---------|
| `codex-shim desktop write-models` | Write bundled matrix to `--output` (default `~/.codex-shim/models.json`). |
| `codex-shim desktop write-models --no-commandcode` | Omit `commandcode-*` rows. |
| `codex-shim desktop write-models --no-cpa-oauth` | Omit `grok-*` rows. |
| `codex-shim patch-app` | Patch macOS `Codex.app` or refresh Linux overlay from `/opt/codex-desktop`. |
| `codex-shim restore-app` | Restore from shim backup (`app.asar` or Linux overlay backup under runtime dir). |

Environment overrides for Linux paths:

- `CODEX_DESKTOP_LINUX_SOURCE_DIR` (default `/opt/codex-desktop`)
- `CODEX_DESKTOP_LINUX_PATCHED_DIR` (default `~/.local/share/codex-desktop-linux-overlay/patched-app`)

## systemd credentials (example)

Map encrypted credential names to the names used in `models.json`:

- `DROID_BYOK_ZAI_CODING_API_KEY`
- `DROID_BYOK_MINIMAX_API_KEY`
- `DROID_BYOK_OPENCODE_GO_API_KEY`
- `XIAOMI_MIMO_TOKEN_PLAN_API_KEY`
- `CROFAI_API_KEY`
- `CLIPROXY_INTERNAL_API_KEY`

Use `LoadCredentialEncrypted=` in the user unit so the shim reads
`$CREDENTIALS_DIRECTORY/<name>` at request time.

## Maintainer workflow

```bash
git fetch origin
git rebase origin/main   # expect conflicts in cli.py / patch needles after Desktop bumps

python3 -m pip install -e ".[dev]"   # or pytest + aiohttp per README
python3 -m pytest tests/ -q

codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
# systemctl --user restart codex-shim.service   # if deployed via user unit
codex-shim status
```

After changing `desktop_models.py`:

1. Regenerate local `models.json` for deploy machines (never commit secrets).
2. Run `test_desktop_model_matrix_*` and catalog tests in `test_settings_catalog.py`.
3. Re-smoke one slug per route class: direct BYOK, `commandcode-*`, `grok-*`, plus one vision row if `no_image_support` changed.

## Syncing with upstream

1. Fetch `origin` (0xSero) and rebase or merge `linux/desktop-provider-bridge`.
2. Run full `pytest`; fork tests concentrate in `tests/test_settings_catalog.py`.
3. Re-run `patch-app` smoke after Codex Desktop version bumps (needle strings in bundled JS change).
4. Keep README fork material minimal; put new fork-only prose in `docs/linux-desktop.md` or this file.

## Publishing

| Item | Value |
|------|--------|
| Remote | `https://github.com/rabesss/codex-shim` |
| Branch | `linux/desktop-provider-bridge` |
| Upstream remote | `origin` → 0xSero/codex-shim |

Coordinate before force-pushing rewritten history.

## Related reading

- [`linux-desktop.md`](linux-desktop.md) — user-facing Linux bridge guide
- [`AUTO_ROUTER.md`](AUTO_ROUTER.md) — upstream Auto Router (unchanged by fork)
- Upstream Codex Desktop release notes — affect `patch-app` bundle needles

## PKG-INFO

`codex_shim.egg-info/PKG-INFO` is generated from `README.md` at package build time.
Edit README and docs only in git; rebuild the editable install to refresh PKG-INFO
locally if needed.