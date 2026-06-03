# Linux Codex Desktop provider bridge

This guide covers the **rabesss/codex-shim** fork branch
`linux/desktop-provider-bridge`, which extends upstream
[0xSero/codex-shim](https://github.com/0xSero/codex-shim) for Codex Desktop on
Linux with a bundled multi-provider BYOK catalog.

Upstream still owns Responses translation, Auto Router, ChatGPT passthrough, and
core daemon behavior. This fork adds catalog generation, credential resolution,
Linux `patch-app`, and provider-prefixed picker labels.

## Architecture

```text
Codex Desktop / CLI  →  codex-shim (127.0.0.1:8765)  →  upstream API
```

| Route class | Example slug prefix | Upstream |
|-------------|---------------------|----------|
| Direct BYOK | `zai-*`, `opencode-go-*`, `minimax-*`, `xiaomi-*`, `crof-*` | Provider `base_url` in `models.json` |
| CommandCode adapter | `commandcode-*` | `http://127.0.0.1:8318/v1` (local adapter; row uses `api_key: "dummy"`) |
| CLIProxyAPI OAuth | `grok-*` | `http://127.0.0.1:8317/v1` via `CLIPROXY_INTERNAL_API_KEY` |

[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) can remain your
general proxy for Cursor and other tools. This fork uses CPA only for OAuth-backed
xAI Grok CLI routes (`grok-*`), not for every model.

## Quick start

1. Install the fork checkout (same as upstream: `pip install -e .`).
2. Write the bundled matrix and regenerate the catalog:

```bash
codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
codex-shim start
```

3. Optional flags on `write-models`:

- `--no-commandcode` — omit `commandcode-*` rows when the adapter on `:8318` is down.
- `--no-cpa-oauth` — omit `grok-*` rows when CPA on `:8317` is down.

4. If the Desktop picker hides custom slugs, patch the Linux overlay (see below).

5. Point your user unit (if any) at decrypted credentials via
`LoadCredentialEncrypted=` so names in `models.json` match runtime files under
`$CREDENTIALS_DIRECTORY`.

## Example slugs

```text
zai-glm-5-1
opencode-go-deepseek-v4-pro
xiaomi-mimo-v2-5-pro
commandcode-deepseek-v4-pro
grok-composer-2-5-fast
```

The matrix stores **credential names only** (for example
`DROID_BYOK_OPENCODE_GO_API_KEY`, `XIAOMI_MIMO_TOKEN_PLAN_API_KEY`,
`CLIPROXY_INTERNAL_API_KEY`). Resolution order is documented in the root
[README](../README.md) (`api_key`, `api_key_env`, `api_key_credential`,
`api_key_file`).

## Desktop picker patch (Linux)

```bash
codex-shim patch-app
# launch Desktop from ~/.local/share/codex-desktop-linux-overlay/patched-app
codex-shim restore-app   # roll back overlay app.asar from shim backup
```

Defaults:

| Role | Path |
|------|------|
| Source install | `/opt/codex-desktop` |
| Patched copy | `~/.local/share/codex-desktop-linux-overlay/patched-app` |

Override with `CODEX_DESKTOP_LINUX_SOURCE_DIR` and
`CODEX_DESKTOP_LINUX_PATCHED_DIR`. Requires `npx` to extract/repack
`resources/app.asar`. `/opt/codex-desktop` is never modified in place.

## Capability policy

Bundled rows set per-model `max_context_limit`, `auto_compact_token_limit`,
`truncation_limit`, and `no_image_support` from smoke-tested behavior where
possible. Treat **Xiaomi Token Plan** as text-only unless your endpoint accepts
image payloads. Enable vision (`no_image_support: false`) only after a live
image request succeeds through the shim for that slug.

## Maintainer documentation

Branch workflow, upstream rebase, full provider families, and test commands:
[`docs/FORK.md`](FORK.md).