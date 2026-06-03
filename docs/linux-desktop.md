# Linux Codex Desktop user guide

This document is the **primary manual** for running **Codex Desktop on Linux** with this
repository (branch `main`). It extends upstream
[0xSero/codex-shim](https://github.com/0xSero/codex-shim) with a bundled multi-provider BYOK
catalog, Linux overlay patching, and provider-prefixed picker labels.

Upstream still owns Responses translation, Auto Router, ChatGPT passthrough, and core daemon
behavior. This fork adds `desktop write-models`, credential-aware settings loading, and
`patch-app` / `restore-app` for the user-local Desktop overlay.

**Maintainers** (rebase, matrix changes, tests): [`docs/FORK.md`](FORK.md).

---

## What you get

| Goal | How the fork helps |
|------|---------------------|
| Many BYOK models in the Desktop picker | Bundled matrix → `~/.codex-shim/models.json` → generated catalog |
| Stable local routing | Shim on `127.0.0.1:8765` translates Codex `/v1/responses` to each upstream API |
| CommandCode and Grok OAuth without plaintext keys in JSON | Rows use `api_key_credential` + systemd `LoadCredentialEncrypted=` |
| Picker shows custom slugs | Optional `patch-app` on a copy of `/opt/codex-desktop` (system install untouched) |

The root [README](../README.md) stays a short entry point; **Linux Desktop setup lives here**.

---

## Architecture

Codex Desktop (or the Codex CLI with managed config) speaks OpenAI **Responses** to the shim.
The shim picks an upstream from the **slug** and `models.json` row, then streams translated
events back to Codex.

```text
┌─────────────────────┐
│  Codex Desktop      │
│  (patched overlay   │
│   or stock build)   │
└──────────┬──────────┘
           │  HTTP  Responses API
           │  http://127.0.0.1:8765/v1/...
           ▼
┌─────────────────────┐
│  codex-shim         │  catalog + routing + translation
│  127.0.0.1:8765     │
└──────────┬──────────┘
           │
     ┌─────┴─────┬─────────────────┬──────────────────┐
     ▼           ▼                 ▼                  ▼
 Direct BYOK   commandcode-*    grok-*           gpt-5.5 (optional)
 provider      :8318            :8317 + CPA       ChatGPT passthrough
 base_url      adapter          OAuth proxy       (~/.codex/auth.json)
```

### Routing rules (slug → upstream)

| Route class | Slug pattern (examples) | Upstream | Auth in `models.json` |
|-------------|-------------------------|----------|------------------------|
| **Direct BYOK** | `zai-*`, `minimax-*`, `opencode-go-*`, `opencode-zen-*`, `xiaomi-*`, `crof-*` | Each row’s `base_url` (vendor API) | `api_key_credential` name (or other resolver fields in README) |
| **CommandCode adapter** | `commandcode-*` | `http://127.0.0.1:8318/v1` | `api_key: "dummy"` (adapter handles auth) |
| **CLIProxyAPI OAuth** | `grok-*` | `http://127.0.0.1:8317/v1` | `CLIPROXY_INTERNAL_API_KEY` via credential file |
| **ChatGPT passthrough** | `gpt-5.5` (upstream naming) | ChatGPT Codex backend | From `~/.codex/auth.json` (not in matrix) |

[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) can stay your general proxy for
Cursor and other tools. **This fork uses CPA on `:8317` only for OAuth-backed Grok CLI routes**
(`grok-*`), not for every model.

---

## Requirements

- **Python 3.11+** and `aiohttp` (installed with the package).
- **Codex Desktop** installed under `/opt/codex-desktop` (typical `.deb` layout).
- **Node `npx`** — required for `patch-app` / `restore-app` (Electron ASAR extract/pack).
- **Local services** when you enable matrix sections:
  - CommandCode (or compatible) OpenAI-compatible API on **port 8318** for `commandcode-*`.
  - CLIProxyAPI on **port 8317** for `grok-*`.
- **Encrypted credentials** (recommended): systemd user unit with `LoadCredentialEncrypted=`
  matching names in `models.json` (see below). Plain `api_key` / `${ENV}` still work per upstream README.

---

## Install

### 1. Clone the fork and install the package

```bash
git clone https://github.com/rabesss/codex-shim.git ~/codex-shim
cd ~/codex-shim
git checkout linux/desktop-provider-bridge   # if not already on the branch
python3 -m pip install --user -e .
```

Ensure `~/.local/bin` is on `PATH` so `codex-shim` is available.

### 2. Paths you will use

| Purpose | Default path |
|---------|----------------|
| Model settings (BYOK matrix) | `~/.codex-shim/models.json` |
| Codex CLI/Desktop config (managed block) | `~/.codex/config.toml` |
| Generated catalog, pid, log (per checkout) | `<repo>/.codex-shim/` |
| System Codex Desktop install (read-only source) | `/opt/codex-desktop` |
| Patched Desktop copy (launch this) | `~/.local/share/codex-desktop-linux-overlay/patched-app` |
| ASAR backups from patch | `<repo>/.codex-shim/linux-app.asar.before-codex-shim-model-picker-patch` |

Override Linux overlay locations with:

- `CODEX_DESKTOP_LINUX_SOURCE_DIR` (default `/opt/codex-desktop`)
- `CODEX_DESKTOP_LINUX_PATCHED_DIR` (default `~/.local/share/codex-desktop-linux-overlay/patched-app`)

### 3. Write the bundled model matrix

```bash
codex-shim desktop write-models --output ~/.codex-shim/models.json
```

This writes **credential names only** (no secret values). Each row includes
`generated_by: codex-shim-desktop-matrix` and a **provider-prefixed slug** (for example
`zai-glm-5-1`, `commandcode-deepseek-v4-pro`).

#### `desktop write-models` flags

| Flag | Effect |
|------|--------|
| `--output PATH` | Destination file (default `~/.codex-shim/models.json`) |
| `--no-commandcode` | Omit all `commandcode-*` rows (use when nothing listens on `:8318`) |
| `--no-cpa-oauth` | Omit all `grok-*` rows (use when CPA is down on `:8317`) |

Help (verified CLI names):

```bash
codex-shim desktop write-models --help
```

A hidden deprecated alias exists for one release cycle: `codex-shim ravish write-models`.
Use `desktop write-models` in scripts and docs.

### 4. Generate catalog and start the shim

```bash
codex-shim generate
codex-shim start
codex-shim status
codex-shim list
```

`generate` reads `--settings` (default `~/.codex-shim/models.json`) and writes:

- `<repo>/.codex-shim/custom_model_catalog.json`
- `<repo>/.codex-shim/config.toml` (opt-in provider snippet)

The daemon listens on **`127.0.0.1:8765`** unless you pass `--port`.

### 5. Wire Codex Desktop to the shim

**One-shot launch** (writes managed config, starts daemon if needed):

```bash
codex-shim app .
```

**Persistent enable** (same managed block, leaves Desktop launch to you):

```bash
codex-shim enable
```

To remove the managed block and stop the daemon:

```bash
codex-shim disable
```

Global CLI flags used by these flows:

- `--settings <path>` — model JSON (default `~/.codex-shim/models.json`)
- `--port <port>` — shim listen port (default `8765`)

---

## systemd credentials (conceptual)

The bundled matrix references **logical credential names**, for example:

- `DROID_BYOK_ZAI_CODING_API_KEY`
- `DROID_BYOK_MINIMAX_API_KEY`
- `DROID_BYOK_OPENCODE_GO_API_KEY`
- `XIAOMI_MIMO_TOKEN_PLAN_API_KEY`
- `CROFAI_API_KEY`
- `CLIPROXY_INTERNAL_API_KEY`

At request time the shim resolves `api_key_credential` in this order (see README for full table):

1. File `$CREDENTIALS_DIRECTORY/<name>` when the process runs under systemd with loaded credentials
2. Environment variable with the same name
3. Other fields (`api_key`, `api_key_env`, `api_key_file`) if you use them instead

**Conceptual user-unit pattern** (no secret values here):

```ini
[Service]
LoadCredentialEncrypted=DROID_BYOK_ZAI_CODING_API_KEY
LoadCredentialEncrypted=CLIPROXY_INTERNAL_API_KEY
# ... one line per name referenced in models.json
ExecStart=%h/.local/bin/codex-shim start
```

After editing encrypted credential files on disk, restart the unit so the shim receives
fresh decrypted material under `/run/user/<uid>/credentials/`.

CommandCode rows intentionally use `api_key: "dummy"` because the adapter on `:8318` performs
its own authentication.

---

## Model slugs and provider families

Slugs are **stable picker IDs**. Upstream `model` IDs and `base_url` live in the same row.

| Family | Example slugs | Credential / notes |
|--------|---------------|-------------------|
| Z.ai Coding | `zai-glm-5-1`, `zai-glm-5`, … | `DROID_BYOK_ZAI_CODING_API_KEY` |
| MiniMax Coding | `minimax-m2-7`, … | `DROID_BYOK_MINIMAX_API_KEY` |
| OpenCode Go | `opencode-go-*` | `DROID_BYOK_OPENCODE_GO_API_KEY` |
| OpenCode Zen | `opencode-zen-*` | same OpenCode Go credential |
| Xiaomi Token Plan | `xiaomi-mimo-*` | `XIAOMI_MIMO_TOKEN_PLAN_API_KEY` |
| CrofAI | `crof-*` | `CROFAI_API_KEY` |
| CommandCode | `commandcode-*` | dummy key; `:8318` |
| Grok via CPA | `grok-composer-2-5-fast`, … | `CLIPROXY_INTERNAL_API_KEY`; `:8317` |

List what the shim will route after `generate`:

```bash
codex-shim list
codex-shim model list
```

---

## Desktop picker patch (`patch-app` / `restore-app`)

Codex Desktop can hide catalog entries behind a server-side allowlist. The shim ships
helpers that patch the Electron bundle so custom slugs appear in the picker and recent
threads behave with the `codex_shim` provider.

### Linux overlay behavior (summary)

1. **`patch-app`** copies `/opt/codex-desktop` → overlay dir when missing or when the
   system `app.asar` hash changed (stamp file in the overlay).
2. Patches `resources/app.asar` (and some `content/` webview assets when present).
3. **`/opt/codex-desktop` is never modified in place.**

```bash
codex-shim patch-app
# Launch Desktop from:
#   ~/.local/share/codex-desktop-linux-overlay/patched-app
```

```bash
codex-shim restore-app
# Restores overlay resources/app.asar from shim backup under <repo>/.codex-shim/
```

Requires **`npx`**. If patch needles no longer match your Desktop version, the command may
fail; see [`docs/FORK.md`](FORK.md) for maintainer rebase notes after Codex bumps.

macOS also supports `patch-app` on `Codex.app`; Linux users should rely on the overlay paths
above.

---

## Choosing and switching models

### CLI defaults in `~/.codex/config.toml`

```bash
codex-shim model use zai-glm-5-1
codex-shim app -m zai-glm-5-1 .
```

`model use` regenerates the catalog, ensures the daemon is running, and updates only the
**shim-managed** block in `~/.codex/config.toml`. Shortcuts if installed: `codex-model`,
`codex-app`.

### HTTP picker (loopback only)

While the daemon runs, open:

- `http://127.0.0.1:8765/picker` — browser UI to switch models
- `GET /api/models` — JSON list
- `POST /api/switch` — body `{"slug":"...", "restart_codex": true|false}`

Picker routes use the same **Host** allowlist as the API (loopback only) to block DNS
rebinding. Display names in Desktop include a **provider suffix** from the fork catalog
(for example `GLM 5.1 - Z.ai Coding`).

### ChatGPT passthrough slug

If `~/.codex/auth.json` contains a valid Codex access token, upstream behavior adds
`gpt-5.5` to the catalog. That route bypasses BYOK rows. Run `codex login` to refresh tokens.

---

## Capability flags (images, context, compaction)

Bundled rows set, per model:

| Field | Role |
|-------|------|
| `max_context_limit` | Advertised context window / compaction input budget |
| `max_output_tokens` | Default cap when translating to Anthropic-shaped APIs |
| `auto_compact_token_limit` | Desktop auto-compaction threshold (matrix-derived) |
| `truncation_limit` | Desktop truncation policy hint |
| `no_image_support` | When true, catalog advertises **text-only** (`input_modalities`) |

**Policy notes:**

- Treat **Xiaomi Token Plan** rows as **text-only** unless you have verified image payloads
  on your endpoint (many token-plan routes reject image input).
- Set `no_image_support: false` only after a live image request succeeds through the shim
  for that slug.
- The catalog flag guides Codex Desktop UX; translation still forwards images if Codex sends
  them unless you add custom guards. See upstream README “Computer use, shell commands, images”.

Regenerate after editing `models.json`:

```bash
codex-shim generate
```

---

## Day-to-day commands (Linux-focused)

```text
codex-shim desktop write-models     Write bundled matrix (--output, --no-commandcode, --no-cpa-oauth)
codex-shim generate                 Build catalog from settings
codex-shim start | stop | restart   Daemon control
codex-shim enable | disable         Persist or remove ~/.codex/config.toml managed block
codex-shim status                   Health + model count
codex-shim list                     Slugs and upstream routes
codex-shim model list | model use   Picker-oriented slug list / set default
codex-shim app [path]               Launch Desktop with shim wired (-m slug)
codex-shim patch-app | restore-app  Linux overlay ASAR patch / rollback
codex-shim codex -- <args>          One-off CLI via inline overrides (no persistent config)
```

`patch-app` and `restore-app` ignore `--settings`.

---

## Troubleshooting

### Shim will not start

```bash
codex-shim status
tail -n 80 <repo>/.codex-shim/shim.log
```

| Symptom | Things to check |
|---------|-----------------|
| Python too old | Need 3.11+ |
| Missing `aiohttp` | Re-run `pip install -e .` in the fork checkout |
| Port in use | `codex-shim --port 8766 restart` and point config at the new port |
| Empty settings | Run `desktop write-models` or `codex login` for passthrough-only |

### Empty catalog / `list` exits with “No models”

1. Confirm `~/.codex-shim/models.json` exists (`desktop write-models`).
2. Run `codex-shim generate` then `codex-shim list`.
3. If using CPA or CommandCode rows, confirm `:8317` / `:8318` services are up—or regenerate
   with `--no-cpa-oauth` / `--no-commandcode`.

### Upstream 401 / credential errors

- Credential name in JSON must match `LoadCredentialEncrypted=` / env name exactly.
- Restart shim (and user unit) after rotating encrypted credentials.
- For `grok-*`, verify CPA and `CLIPROXY_INTERNAL_API_KEY`.
- For `commandcode-*`, verify the adapter on `:8318` (dummy key is expected).

### Desktop picker shows only `default`

1. `codex-shim generate` and `codex-shim model list` — confirm slugs exist locally.
2. `codex-shim enable` or `codex-shim app` — confirm managed provider in `~/.codex/config.toml`.
3. Run `codex-shim patch-app` and launch the **overlay** binary, not only `/opt/codex-desktop`.
4. Re-patch after upgrading Codex Desktop (JS bundle needles change).

### Model in picker but requests 404

Slug not in the **current** generated catalog. Edit `models.json`, then:

```bash
codex-shim generate
codex-shim model use <slug>
```

### Tool calls degrade to plain text

Confirm routing with `tail -f <repo>/.codex-shim/shim.log`. BYOK providers vary in tool-call
quality; ChatGPT passthrough remains the highest-fidelity path (see upstream README).

### `patch-app` fails or Desktop crashes after patch

```bash
codex-shim restore-app
```

Compare your installed Desktop version with fork maintainer notes in [`docs/FORK.md`](FORK.md).
Restore does not delete the overlay directory; it rewinds `app.asar` from the shim backup.

---

## What this fork does **not** solve

| Topic | Notes |
|-------|--------|
| **Codex subagents / `multi_agent`** | Implemented by the Codex app runtime, not `codex-shim`. BYOK routes may return “unsupported call” for subagent tools even when they appear in schema. Enabling `[features].multi_agent` in `~/.codex/config.toml` does not make every upstream execute subagents. |
| **Upstream tool-call quality** | The shim translates API shapes; it cannot force a provider to emit valid tool JSON. |
| **MSIX / Store Desktop builds** | Linux guide assumes `/opt/codex-desktop` + overlay; Windows Store allowlist issues are upstream Desktop behavior (see README). |
| **Internet-exposed shim** | Default bind is loopback; do not expose `:8765` without hardening. |

For product-level limitations (ASAR patch sensitivity, ChatGPT endpoint changes), see upstream
README **Limitations**.

---

## Related documentation

| Document | Audience |
|----------|----------|
| [`docs/FORK.md`](FORK.md) | Maintainers: rebase, matrix source, tests, publishing |
| [README](../README.md) | Upstream install, translation, Auto Router, security |
| [`docs/AUTO_ROUTER.md`](AUTO_ROUTER.md) | Optional smart routing (unchanged by fork) |

---

## Quick reference workflow

```bash
# Install + matrix
pip install -e ~/codex-shim
codex-shim desktop write-models
codex-shim generate && codex-shim start

# Desktop overlay + launch
codex-shim patch-app
codex-shim enable    # or: codex-shim app .

# Switch model
codex-shim model use opencode-go-deepseek-v4-pro
```

After changing `desktop_models.py` or upgrading Codex Desktop, maintainers should follow
[`docs/FORK.md`](FORK.md) before deploying updated catalogs to daily-driver machines.