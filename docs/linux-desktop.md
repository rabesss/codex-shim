# Linux Codex Desktop user guide

This document is the **primary manual** for running **Codex Desktop on Linux** with this
repository (branch `main`). It targets
[ilysenko/codex-desktop-linux](https://github.com/ilysenko/codex-desktop-linux) installs
under `/opt/codex-desktop`. It extends upstream
[0xSero/codex-shim](https://github.com/0xSero/codex-shim) with a CLIProxyAPI-backed
custom-model catalog, Linux overlay patching, Linux launcher/restart behavior, and
route-first picker labels.

Upstream still owns Responses translation, Auto Router, ChatGPT passthrough, and core daemon
behavior where it remains applicable. This fork adds `desktop write-models`,
credential-aware settings loading, and Linux-only `patch-app` / `restore-app` for the
user-local Desktop overlay.

**Maintainers** (rebase, matrix changes, tests): [`docs/FORK.md`](FORK.md).

---

## What you get

| Goal | How the fork helps |
|------|---------------------|
| Many custom models in the Desktop picker | CLIProxyAPI discovery/bootstrap → `~/.codex-shim/models.json` → generated catalog |
| Stable local routing | Shim on `127.0.0.1:8765` translates Codex `/v1/responses` to CLIProxyAPI-compatible chat routes |
| CommandCode, Grok OAuth, hosted providers, and local models without plaintext keys in JSON | Rows use `api_key_credential: CLIPROXY_INTERNAL_API_KEY`; provider keys stay in CLIProxyAPI |
| Picker shows custom slugs | Optional `patch-app` on a copy of `/opt/codex-desktop` (system install untouched) |

The root [README](../README.md) stays a short entry point; **Linux Desktop setup lives here**.

---

## Architecture

Codex Desktop (or the Codex CLI with managed config) speaks OpenAI **Responses** to the shim.
The shim picks a **slug** from `models.json`, translates Codex requests into OpenAI-compatible
chat calls, and sends those calls to CLIProxyAPI. CLIProxyAPI owns provider-specific auth,
OAuth refresh, local model routing, and adapters such as CommandCode.

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
     ┌───────────┴───────────┐              ┌──────────────────┐
     ▼                       ▼              ▼
 CLIProxyAPI :8317       route metadata   gpt-5.5 (optional)
 hosted providers /      + capability     ChatGPT passthrough
 OAuth / local routes    overrides        (~/.codex/auth.json)
 local / CommandCode
```

### Routing rules (slug → upstream)

| Route class | Slug pattern (examples) | Upstream | Auth in `models.json` |
|-------------|-------------------------|----------|------------------------|
| **CLIProxyAPI custom routes** | `opencode-go-*`, `commandcode-*`, `grok-*`, `zai-coding-*`, `minimax-coding-*`, `crofai-*` | `http://127.0.0.1:8317/v1` | `CLIPROXY_INTERNAL_API_KEY` via credential file or env |
| **ChatGPT passthrough** | `gpt-5.5` (upstream naming, explicitly enabled) | ChatGPT Codex backend | From `~/.codex/auth.json` (not in matrix) |

[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) can stay your general proxy for
Cursor and other tools. **This fork treats CPA on `:8317` as the source of truth for custom
models.** codex-shim does not implement provider-specific adapters; it only converts CPA route
metadata plus Codex capability overrides into Desktop/CLI-compatible catalog rows.

---

## Requirements

- **Python 3.11+** and `aiohttp` (installed with the package).
- **Codex Desktop** installed under `/opt/codex-desktop` (typical `.deb` layout).
- **Node `npx`** — required for `patch-app` / `restore-app` (Electron ASAR extract/pack).
- **Local service:** CLIProxyAPI on **port 8317** for generated custom-model rows.
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
| Model settings (custom-model matrix) | `~/.codex-shim/models.json` |
| Shim profile config (opt-in custom mode) | `~/.codex/codex-shim.config.toml` |
| Shim Codex CLI wrapper | `~/.local/bin/codex-shim-profile-codex` |
| Shim Desktop launcher wrapper | `~/.local/bin/codex-desktop-shim` |
| Generated catalog, pid, log (per checkout) | `<repo>/.codex-shim/` |
| System Codex Desktop install (read-only source) | `/opt/codex-desktop` |
| Patched Desktop copy (launch this) | `~/.local/share/codex-desktop-linux-overlay/patched-app` |
| ASAR backups from patch | `<repo>/.codex-shim/linux-app.asar.before-codex-shim-model-picker-patch` |

Override Linux overlay locations with:

- `CODEX_DESKTOP_LINUX_SOURCE_DIR` (default `/opt/codex-desktop`)
- `CODEX_DESKTOP_LINUX_PATCHED_DIR` (default `~/.local/share/codex-desktop-linux-overlay/patched-app`)

### 3. Write the CLIProxyAPI-backed model matrix

```bash
codex-shim desktop write-models --output ~/.codex-shim/models.json
```

This writes **credential names only** (no secret values). When
`CLIPROXY_INTERNAL_API_KEY` is present in the environment, the command discovers current
chat-capable routes from CLIProxyAPI `/v1/models`; otherwise it writes a bootstrap route set.
Each row includes `generated_by: codex-shim-cliproxyapi-discovery`, a route-prefixed slug
(for example `opencode-go-deepseek-v4-pro`, `commandcode-deepseek-v4-pro`), and Codex
capability metadata for image/tool/reasoning surfaces.

#### `desktop write-models` flags

| Flag | Effect |
|------|--------|
| `--output PATH` | Destination file (default `~/.codex-shim/models.json`) |
| `--no-commandcode` | Omit CLIProxyAPI rows whose owner is `commandcode` |
| `--no-cpa-oauth` | Omit CLIProxyAPI rows whose owner is `xai` / Grok OAuth |

Help (verified CLI names):

```bash
codex-shim desktop write-models --help
```

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

**One-shot launch** (writes the shim profile/wrapper, starts daemon if needed, then launches
Desktop through the wrapper):

```bash
codex-shim app .
```

**Persistent enable** (writes the same shim profile/wrapper, leaves Desktop launch to you):

```bash
codex-shim enable
```

To remove the shim profile/wrapper and stop the daemon:

```bash
codex-shim disable
```

Global CLI flags used by these flows:

- `--settings <path>` — model JSON (default `~/.codex-shim/models.json`)
- `--port <port>` — shim listen port (default `8765`)

---

## systemd credentials (conceptual)

The generated matrix references one logical credential name:

- `CLIPROXY_INTERNAL_API_KEY`

Provider keys such as Z.ai, MiniMax, OpenCode, Xiaomi, CrofAI, CommandCode, or OAuth-backed
Grok credentials belong to CLIProxyAPI and its service/config, not to `models.json`.

At request time the shim resolves `api_key_credential` in this order (see README for full table):

1. File `$CREDENTIALS_DIRECTORY/<name>` when the process runs under systemd with loaded credentials
2. Environment variable with the same name
3. Other fields (`api_key`, `api_key_env`, `api_key_file`) if you use them instead

**Conceptual user-unit pattern** (no secret values here):

```ini
[Service]
LoadCredentialEncrypted=CLIPROXY_INTERNAL_API_KEY
# ... one line per name referenced in models.json
ExecStart=%h/.local/bin/codex-shim start
```

After editing encrypted credential files on disk, restart the unit so the shim receives
fresh decrypted material under `/run/user/<uid>/credentials/`.

For codex-shim itself, `CLIPROXY_INTERNAL_API_KEY` is enough. CLIProxyAPI can load its own
provider credentials in its own user service.

---

## Model slugs and provider families

Slugs are **stable picker IDs**. Upstream `model` IDs and `base_url` live in the same row.

| Family | Example slugs | Credential / notes |
|--------|---------------|-------------------|
| Z.ai Coding | `zai-coding-glm-5-1`, `zai-coding-glm-5`, … | routed through CLIProxyAPI |
| MiniMax Coding | `minimax-coding-minimax-m3`, … | routed through CLIProxyAPI |
| OpenCode Go | `opencode-go-*` | routed through CLIProxyAPI |
| OpenCode Zen | `opencode-zen-*` | routed through CLIProxyAPI |
| CrofAI | `crofai-*` | routed through CLIProxyAPI |
| CommandCode | `commandcode-*` | routed through CLIProxyAPI; no native adapter in codex-shim |
| Grok via CPA | `grok-composer-2-5-fast`, … | routed through CLIProxyAPI OAuth |

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

This fork does not patch macOS `.app` bundles or Windows packages. Use upstream
`0xSero/codex-shim` if you need non-Linux platform support.

---

## Choosing and switching models

### Shim profile defaults

```bash
codex-shim model use opencode-go-deepseek-v4-pro
codex-shim app -m opencode-go-deepseek-v4-pro .
```

`model use` regenerates the catalog, ensures the daemon is running, and updates the
opt-in shim profile/wrapper. It does not mutate global `~/.codex/config.toml`, so normal
`codex` stays official/direct unless you explicitly use the shim wrapper. Shortcuts if
installed: `codex-model`, `codex-app`.

### HTTP picker (loopback only)

While the daemon runs, open:

- `http://127.0.0.1:8765/picker` — browser UI to switch models
- `GET /api/models` — JSON list
- `POST /api/switch` — body `{"slug":"...", "restart_codex": true|false}`

Picker routes use the same **Host** allowlist as the API (loopback only) to block DNS
rebinding. Display names in Desktop are **route-first** from the fork catalog
(for example `CLIProxyAPI / OpenCode Go / DeepSeek V4 Pro`).

### ChatGPT passthrough slug

If `CODEX_SHIM_ENABLE_CHATGPT=1` is set and `~/.codex/auth.json` contains a valid Codex
access token, upstream behavior adds `gpt-5.5` to the catalog. That route bypasses
CLIProxyAPI rows. Run `codex login` to refresh tokens.

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
| `supports_tools` | When false, catalog disables parallel tool-call support for that model |
| `supports_reasoning` | When false, catalog disables reasoning-summary support for that model |
| `supports_streaming` | Records whether the route is expected to stream through CLIProxyAPI |

**Policy notes:**

- Set `no_image_support: false` only after a live image request succeeds through the shim
  for that slug.
- Leave `supports_tools` / `supports_reasoning` false for routes where CLIProxyAPI or the
  upstream model cannot produce the corresponding Codex-compatible behavior.
- The catalog flags guide Codex Desktop UX; translation still forwards payloads if Codex sends
  them unless you add custom guards. See upstream README “Computer use, shell commands, images”.

Regenerate after editing `models.json`:

```bash
codex-shim generate
```

---

## Day-to-day commands (Linux-focused)

```text
codex-shim desktop write-models     Write CLIProxyAPI matrix (--output, --no-commandcode, --no-cpa-oauth)
codex-shim generate                 Build catalog from settings
codex-shim start | stop | restart   Daemon control
codex-shim enable | disable         Persist or remove shim profile/wrappers
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
3. Confirm CLIProxyAPI is up on `:8317` and `CLIPROXY_INTERNAL_API_KEY` decrypts.
   Regenerate with `--no-cpa-oauth` / `--no-commandcode` to omit either route class.

### Upstream 401 / credential errors

- Credential name in JSON must match `LoadCredentialEncrypted=` / env name exactly.
- Restart shim (and user unit) after rotating encrypted credentials.
- For any generated custom route, verify CLIProxyAPI and `CLIPROXY_INTERNAL_API_KEY`.
- For `commandcode-*`, verify the CommandCode route exists in CLIProxyAPI; codex-shim does
  not talk directly to `https://api.commandcode.ai/alpha/generate`.

### Desktop picker shows only `default`

1. `codex-shim generate` and `codex-shim model list` — confirm slugs exist locally.
2. `codex-shim enable` or `codex-shim app` — confirm `~/.codex/codex-shim.config.toml` and wrapper files exist.
3. Run `codex-shim patch-app` and launch the **overlay** binary, not only `/opt/codex-desktop`.
4. Re-patch after upgrading Codex Desktop (JS bundle needles change).

### Model in picker but requests 404

Slug not in the **current** generated catalog. Edit `models.json`, then:

```bash
codex-shim generate
codex-shim model use <slug>
```

### Tool calls degrade to plain text

Confirm routing with `tail -f <repo>/.codex-shim/shim.log`. CLIProxyAPI routes vary in
tool-call quality; ChatGPT passthrough remains the highest-fidelity path when explicitly
enabled (see upstream README).

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
| **Codex subagents / `multi_agent`** | Implemented by the Codex app runtime, not `codex-shim`. CLIProxyAPI routes may return “unsupported call” for subagent tools even when they appear in schema. Enabling `[features].multi_agent` in `~/.codex/config.toml` does not make every upstream execute subagents. |
| **Upstream tool-call quality** | The shim translates API shapes; it cannot force a provider to emit valid tool JSON. |
| **Non-Linux Desktop builds** | This fork assumes `/opt/codex-desktop` + overlay from `ilysenko/codex-desktop-linux`. Non-Linux package formats belong upstream. |
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
```

The maintained Linux Desktop overlay now has a single-app custom-model bridge:
Desktop reads `http://127.0.0.1:8765/api/models` for picker rows and injects
`codex_shim` only for selected custom slugs. The older `codex-shim app`,
`codex-shim model use`, and `codex-shim patch-app` flows remain useful for
legacy fallback/debugging, but they are not the primary path for a maintained
workstation build.

After changing `desktop_models.py` or upgrading Codex Desktop, maintainers should follow
[`docs/FORK.md`](FORK.md) before deploying updated catalogs to daily-driver machines.
