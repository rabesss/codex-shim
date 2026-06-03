# codex-shim (Linux Codex Desktop)

This repository is a **maintained fork** of [0xSero/codex-shim](https://github.com/0xSero/codex-shim) focused on **Codex Desktop on Linux**: a local Python shim that exposes an OpenAI Responses-compatible endpoint on loopback, plus a **bundled multi-provider BYOK model matrix** (`codex-shim desktop write-models`) so Desktop can route to Z.ai, OpenCode, MiniMax, Xiaomi Token Plan, CommandCode, CLIProxyAPI Grok, and related upstreams without rebuilding Codex.

Codex Desktop or CLI talks to the shim; the shim translates streaming traffic to each provider’s API shape and back.

**Full setup, architecture, credentials, and picker patching:** [`docs/linux-desktop.md`](docs/linux-desktop.md)  
**Fork maintenance, matrix changes, upstream rebase:** [`docs/FORK.md`](docs/FORK.md)

---

## Who this is for

- You run **Codex Desktop for Linux** (typically under `/opt/codex-desktop`) and want **first-class custom models** in the picker.
- You bring your own API keys or local proxies (CommandCode on `:8318`, CLIProxyAPI for `grok-*` on `:8317`, etc.) and are fine editing `~/.codex-shim/models.json` or regenerating it from the bundled matrix.

This README is the **entry point**. It does not cover macOS ASAR workflows, Windows MSIX, Cursor Composer passthrough, or generic upstream theory—see upstream for that.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.11+** | Install the package editable from this checkout. |
| **Codex Desktop (Linux)** | Installed and authenticated; shim does not replace Codex itself. |
| **Provider credentials** | Env vars, `api_key_credential` names, or files—see linux-desktop guide. |
| **Optional: `npx`** | Needed only if you run `codex-shim patch-app` when Desktop hides custom slugs. |
| **Optional: systemd user unit** | Run `codex-shim start` via a service; map secrets with `LoadCredentialEncrypted=` (documented in FORK.md). |

---

## Quick start

Clone this fork (`main` on [rabesss/codex-shim](https://github.com/rabesss/codex-shim)), install, write the desktop matrix, generate catalog, and start the daemon:

```bash
git clone https://github.com/rabesss/codex-shim.git ~/codex-shim
cd ~/codex-shim
python3 -m pip install -e .
```

```bash
codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
codex-shim start
```

Point Codex at the shim (managed config):

```bash
codex-shim enable    # writes shim blocks to ~/.codex/config.toml
codex-shim status    # health on loopback (default 127.0.0.1:8765)
```

**Picker still missing custom models?** Run `codex-shim patch-app` to refresh the Linux overlay under `~/.local/share/codex-desktop-linux-overlay/patched-app` and launch Desktop from that copy—details in [`docs/linux-desktop.md`](docs/linux-desktop.md). Roll back with `codex-shim restore-app`.

**Matrix flags:** `--no-commandcode` and `--no-cpa-oauth` on `desktop write-models` omit rows when local adapters are down.

**Example slugs:** `zai-glm-5-1`, `opencode-go-deepseek-v4-pro`, `xiaomi-mimo-v2-5-pro`, `commandcode-deepseek-v4-pro`, `grok-composer-2-5-fast`.

---

## How routing works (short)

```text
Codex Desktop / CLI  →  codex-shim (127.0.0.1:8765)  →  upstream API
```

| Route class | Slug prefix (examples) | Upstream |
|-------------|----------------------|----------|
| Direct BYOK | `zai-*`, `opencode-*`, `minimax-*`, `xiaomi-*`, `crof-*` | Provider `base_url` in `models.json` |
| CommandCode | `commandcode-*` | `http://127.0.0.1:8318/v1` |
| CLIProxyAPI OAuth | `grok-*` | `http://127.0.0.1:8317/v1` |

Credential fields in settings: `api_key`, `api_key_env`, `api_key_credential`, `api_key_file` (resolution order and systemd examples in the linked docs).

---

## Upstream

Core shim behavior—Responses translation, ChatGPT passthrough, Auto Router, provider adapters, and cross-platform install notes—lives in **[0xSero/codex-shim](https://github.com/0xSero/codex-shim)**. Rebase this fork onto `origin/main` when pulling upstream fixes; keep Linux-only deltas in `codex_shim/desktop_models.py`, Linux `patch-app`, and [`docs/FORK.md`](docs/FORK.md).

---

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -q
```

---

## License

MIT — see `LICENSE`.

Codex Desktop is a trademark of OpenAI. This project is unaffiliated.