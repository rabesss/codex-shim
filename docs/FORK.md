# Fork maintenance: Linux desktop CLIProxyAPI bridge

Maintainer notes for **this repository**, rebased onto upstream
**[0xSero/codex-shim](https://github.com/0xSero/codex-shim)** (`origin` → `origin/main`).

## Documentation layout

| Audience | Document | Role |
|----------|----------|------|
| Public / first visit | [README](../README.md) | Fork identity and delta vs upstream; not a copy of the upstream mega-README |
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
| `codex_shim/desktop_models.py` | **New.** CLIProxyAPI discovery/bootstrap `models.json` matrix (`desktop_models_payload`, `write_desktop_models`). |
| `codex_shim/cli.py` | `desktop write-models`; Linux `patch-app` / `restore-app`; multi-variant Desktop JS needles; health check timeout 3s. |
| `codex_shim/settings.py` | `api_key_env`, `api_key_credential`, `api_key_file`; `$CREDENTIALS_DIRECTORY` + env fallback; `auto_compact_token_limit`, `truncation_limit`; no silent Cursor key fallback on empty `api_key`. |
| `codex_shim/catalog.py` | Route-first `Provider / Model` `display_name`; `provider_display_name` from CLIProxyAPI route metadata; capability flags for image/tool/reasoning surfaces. |
| `codex_shim/server.py` | Credential error text; versioned `/vN` base URL join. Provider-specific adapters remain in CLIProxyAPI. |
| `tests/test_settings_catalog.py` | CLIProxyAPI matrix, credentials, catalog labels, Linux bundle patch tests, discovery filtering. |
| `tests/test_server.py` | Upstream Responses/chat routing tests. |

**Documentation on the fork branch:** `README.md` (fork identity / delta), `docs/linux-desktop.md`, `docs/FORK.md`.

## Fork-only behavior (summary)

| Area | Maintainer note |
|------|-----------------|
| Matrix | `codex-shim desktop write-models` → default `~/.codex-shim/models.json`; live CLIProxyAPI discovery when `CLIPROXY_INTERNAL_API_KEY` is in the environment; bootstrap fallback otherwise. |
| Matrix source | CLIProxyAPI `/v1/models` is the source of truth. `desktop_models.py` owns slug cleanup and Codex capability overrides only. |
| Credentials | Generated rows use `api_key_credential: CLIPROXY_INTERNAL_API_KEY`; provider keys stay in CLIProxyAPI. User setup → [`linux-desktop.md`](linux-desktop.md). |
| Desktop picker | Linux-only `patch-app` / `restore-app` for the `codex-desktop-linux` overlay (`CODEX_DESKTOP_LINUX_*` env overrides). |
| Catalog | Picker labels use route-first `Provider / Model` names; compaction/truncation limits from settings. |

## CLI surface (fork-specific)

| Command | Purpose |
|---------|---------|
| `codex-shim desktop write-models` | Write CLIProxyAPI-backed matrix (`--output`, `--no-commandcode`, `--no-cpa-oauth`). |
| `codex-shim patch-app` | Refresh and patch Linux overlay from `/opt/codex-desktop`. |
| `codex-shim restore-app` | Restore Linux overlay `app.asar` from shim backup. |

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

1. Regenerate local `models.json` on deploy machines (never commit secrets). Use a CLIProxyAPI internal key in the environment when you want live discovery.
2. Run `test_desktop_model_matrix_*` and catalog tests in `tests/test_settings_catalog.py`.
3. Smoke one slug per CLIProxyAPI route family: `opencode-go-*`, `commandcode-*`, `grok-*`, plus one vision row if `no_image_support` changed.

End-user deploy steps: [`linux-desktop.md`](linux-desktop.md).

## Syncing with upstream

1. `git fetch origin` and rebase (or merge) the fork branch onto `origin/main`.
2. Full `pytest`; fork regressions concentrate in `tests/test_settings_catalog.py`.
3. Re-run `patch-app` smoke after Codex Desktop version bumps (needle strings in bundled JS change).
4. Keep README focused on fork identity and delta; new operational user prose belongs in `docs/linux-desktop.md`, not README or this file.

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
