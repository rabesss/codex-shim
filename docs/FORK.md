# Fork maintenance: Linux desktop provider bridge

Maintainer notes for **[rabesss/codex-shim](https://github.com/rabesss/codex-shim)**, rebased onto upstream
**[0xSero/codex-shim](https://github.com/0xSero/codex-shim)** (`origin` → `origin/main`).

## Documentation layout

| Audience | Document | Role |
|----------|----------|------|
| Public / first visit | [README](../README.md) | Minimal project face: upstream install, core commands, short fork pointer |
| Linux bridge users | [`linux-desktop.md`](linux-desktop.md) | Quick start, routing, `patch-app`, credentials, capability policy |
| Fork maintainers | This file | Delta vs upstream, rebase workflow, tests, publishing |

Do not duplicate user-guide prose here; link to [`linux-desktop.md`](linux-desktop.md) instead.

Upstream-only topics (Auto Router, subscription passthrough, full README depth): stay in upstream docs — e.g. [`AUTO_ROUTER.md`](AUTO_ROUTER.md).

## Fork delta vs `origin/main`

Refresh the diff after every rebase:

```bash
git fetch origin
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- ':!*.md' ':!docs/*'
```

**Code and tests** (branch tip; re-run `--stat` after rebase):

| File | Change |
|------|--------|
| `codex_shim/desktop_models.py` | **New.** Bundled `models.json` matrix (`desktop_models_payload`, `write_desktop_models`). |
| `codex_shim/cli.py` | `desktop write-models`; hidden deprecated `ravish write-models`; Linux `patch-app` / `restore-app`; multi-variant Desktop JS needles; health check timeout 3s. |
| `codex_shim/settings.py` | `api_key_env`, `api_key_credential`, `api_key_file`; `$CREDENTIALS_DIRECTORY` + env fallback; `auto_compact_token_limit`, `truncation_limit`; no silent Cursor key fallback on empty `api_key`. |
| `codex_shim/catalog.py` | Provider suffix on `display_name`; `provider_display_name` from settings; CommandCode/CLIProxyAPI labels from `base_url`; reasoning summary defaults. |
| `codex_shim/server.py` | Credential error text; versioned `/vN` base URL join. |
| `tests/test_settings_catalog.py` | Desktop matrix, credentials, catalog labels, Linux bundle patch tests. |
| `tests/test_server.py` | Minor server test adjustment. |

**Documentation on the fork branch:** `README.md` (upstream-aligned + short fork pointer), `docs/linux-desktop.md`, `docs/FORK.md`.

## Fork-only behavior (summary)

| Area | Maintainer note |
|------|-----------------|
| Matrix | `codex-shim desktop write-models` → default `~/.codex-shim/models.json`; optional `--no-commandcode`, `--no-cpa-oauth`. |
| Matrix source | Provider families and slug policy live in `desktop_models.py`; user-facing route table → [`linux-desktop.md`](linux-desktop.md). |
| Credentials | Rows use `api_key_credential` names; CommandCode uses `api_key: "dummy"`. User setup → [`linux-desktop.md`](linux-desktop.md). |
| Desktop picker | `patch-app` / `restore-app` for macOS bundle or Linux overlay (`CODEX_DESKTOP_LINUX_*` env overrides). |
| Catalog | Picker labels gain ` - Provider` suffix; compaction/truncation limits from settings. |

`codex-shim ravish write-models` remains hidden (`argparse.SUPPRESS`) for one release cycle; scripts must use `desktop write-models`.

## CLI surface (fork-specific)

| Command | Purpose |
|---------|---------|
| `codex-shim desktop write-models` | Write bundled matrix (`--output`, `--no-commandcode`, `--no-cpa-oauth`). |
| `codex-shim patch-app` | Patch macOS `Codex.app` or refresh Linux overlay from `/opt/codex-desktop`. |
| `codex-shim restore-app` | Restore from shim backup (`app.asar` or Linux overlay backup). |

## Maintainer workflow

```bash
git fetch origin
git rebase origin/main   # conflicts often in cli.py / patch needles after Desktop bumps

python3 -m pip install -e ".[dev]"   # or pytest + aiohttp per README
python3 -m pytest tests/ -q

codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
# systemctl --user restart codex-shim.service   # if deployed via user unit
codex-shim status
```

After changing `desktop_models.py`:

1. Regenerate local `models.json` on deploy machines (never commit secrets).
2. Run `test_desktop_model_matrix_*` and catalog tests in `tests/test_settings_catalog.py`.
3. Smoke one slug per route class: direct BYOK, `commandcode-*`, `grok-*`, plus one vision row if `no_image_support` changed.

End-user deploy steps: [`linux-desktop.md`](linux-desktop.md).

## Syncing with upstream

1. `git fetch origin` and rebase (or merge) the fork branch onto `origin/main`.
2. Full `pytest`; fork regressions concentrate in `tests/test_settings_catalog.py`.
3. Re-run `patch-app` smoke after Codex Desktop version bumps (needle strings in bundled JS change).
4. Keep README fork material minimal; new user-facing fork prose belongs in `docs/linux-desktop.md`, not README or this file.

## Publishing

| Item | Value |
|------|--------|
| Fork remote | `https://github.com/rabesss/codex-shim` (`git remote` name: `fork`) |
| Fork default branch | `main` |
| Upstream remote | `origin` → `0xSero/codex-shim` |

```bash
git push fork main
```

Coordinate before force-pushing rewritten history. Feature work may also live on `linux/desktop-provider-bridge`; merge to `main` before publishing unless you intentionally ship only the feature branch.

## PKG-INFO

`codex_shim.egg-info/PKG-INFO` is **generated from `README.md` at package build time** (setuptools reads the README long description). Edit `README.md` and docs in git only; rebuild the editable install (`pip install -e .`) to refresh local `PKG-INFO` if you inspect it. Do not treat `PKG-INFO` as the source of truth for fork user docs — use [`linux-desktop.md`](linux-desktop.md).

## Related reading

- [`linux-desktop.md`](linux-desktop.md) — Linux bridge user guide
- [`AUTO_ROUTER.md`](AUTO_ROUTER.md) — upstream Auto Router (unchanged by fork)
- Upstream Codex Desktop release notes — affect `patch-app` bundle needles