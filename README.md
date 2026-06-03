# codex-shim — Linux Codex Desktop provider bridge (rabesss fork)

**Maintained fork** of [0xSero/codex-shim](https://github.com/0xSero/codex-shim) for **Codex Desktop on Linux**: loopback Responses shim plus a **bundled BYOK model matrix** and Linux overlay tooling so Desktop can use Z.ai, OpenCode, MiniMax, Xiaomi Token Plan, CommandCode, CLIProxyAPI Grok, and related routes without hand-authoring every `models.json` row.

---

## Use case

| Situation | Where to go |
|-----------|-------------|
| You want the **generic** cross-platform shim (theory, macOS ASAR, Windows MSIX, Cursor, Auto Router, full upstream README) | Clone **[0xSero/codex-shim](https://github.com/0xSero/codex-shim)** — that repo is the canonical home for install depth and platform guides. |
| You run **Codex Desktop for Linux** (`/opt/codex-desktop`), bring your own keys or local proxies, and want **first-class custom models** in the picker with fork-maintained matrix + `patch-app` | Use **this fork** ([rabesss/codex-shim](https://github.com/rabesss/codex-shim)). |

This README explains **what the fork is and how it differs from upstream**. It is not a shortened copy of the upstream mega-README.

---

## How this differs from `0xSero/main`

| Layer | Upstream (`origin/main`) | This fork (`main`) |
|-------|--------------------------|---------------------|
| Core engine | Responses translation, daemon, `generate` / `start` / `enable`, provider adapters, ChatGPT passthrough, Auto Router docs | **Same core** — rebased onto upstream; fixes flow in via `origin/main`. |
| Desktop matrix | You maintain `models.json` yourself | **`codex_shim/desktop_models.py`** + `codex-shim desktop write-models` → bundled multi-provider matrix |
| Credentials | Standard `api_key` / env patterns | **`api_key_env`**, **`api_key_credential`** (systemd `LoadCredentialEncrypted=`), **`api_key_file`**; no silent Cursor fallback on empty key |
| Catalog / picker labels | Upstream display rules | **Provider suffix** on `display_name`; CommandCode / CLIProxyAPI labels from `base_url`; compaction / truncation limits from settings |
| Codex Desktop UI | macOS `patch-app` on `.app`; upstream Linux notes vary | **Linux `patch-app` / `restore-app`** for user-local overlay under `~/.local/share/codex-desktop-linux-overlay/`; multi-variant JS needles |
| User documentation | Full README + platform guides on upstream | **[`docs/linux-desktop.md`](docs/linux-desktop.md)** (operational manual); this README (fork identity only) |
| Maintainer documentation | Upstream contribution flow | **[`docs/FORK.md`](docs/FORK.md)** (delta, rebase, tests, publishing) |

---

## What this fork adds

Changes on this branch relative to **`origin/main`** (refresh with `git diff origin/main...HEAD` after rebase):

| Area | What shipped |
|------|----------------|
| **`codex_shim/desktop_models.py`** | New module: bundled `models.json` payload (`desktop_models_payload`, `write_desktop_models`). |
| **CLI** | `codex-shim desktop write-models` (`--output`, `--no-commandcode`, `--no-cpa-oauth`); hidden deprecated `ravish write-models`; Linux-aware **`patch-app`** / **`restore-app`**; health check timeout 3s. |
| **`codex_shim/settings.py`** | Credential resolution order; `$CREDENTIALS_DIRECTORY` support; `auto_compact_token_limit`, `truncation_limit`. |
| **`codex_shim/catalog.py`** | Picker `display_name` + provider labels; reasoning summary defaults. |
| **`codex_shim/server.py`** | Clearer credential errors; versioned `/vN` base URL join. |
| **Tests** | `tests/test_settings_catalog.py` (matrix, credentials, catalog, Linux bundle patch); `tests/test_server.py` adjustments. |
| **Docs** | [`docs/linux-desktop.md`](docs/linux-desktop.md) — architecture, routing, credentials, capability policy, full `patch-app` procedure; [`docs/FORK.md`](docs/FORK.md) — maintainer playbook. |

**Example matrix slugs:** `zai-glm-5-1`, `opencode-go-deepseek-v4-pro`, `xiaomi-mimo-v2-5-pro`, `commandcode-deepseek-v4-pro`, `grok-composer-2-5-fast`.

---

## What we do not maintain here

- The **upstream long README** is not the face of this repository — generic install, subscription passthrough, Cursor Composer, Auto Router, macOS/Windows workflows, and cross-platform theory stay on **[0xSero/codex-shim](https://github.com/0xSero/codex-shim)**.
- **Operational depth** (systemd units, overlay paths, troubleshooting, full `patch-app` steps, credential file layout) lives only in **[`docs/linux-desktop.md`](docs/linux-desktop.md)** — not duplicated below.

When you need upstream behavior or docs, use upstream; when you need Linux Desktop + this matrix, use this fork and the linux-desktop guide.

---

## Quick start

```bash
git clone https://github.com/rabesss/codex-shim.git ~/codex-shim
cd ~/codex-shim
python3 -m pip install -e .

codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
codex-shim start
codex-shim enable    # managed ~/.codex/config.toml
codex-shim status    # loopback health (default 127.0.0.1:8765)
```

**Everything after install** — routing table, credentials, `patch-app`, Desktop launch from overlay, flags, smoke tests — is in **[`docs/linux-desktop.md`](docs/linux-desktop.md)**.

---

## Documentation map

| Document | Audience | Role |
|----------|----------|------|
| **README.md** (this file) | Visitors choosing a repo | Fork identity, delta vs upstream, what to clone |
| **[`docs/linux-desktop.md`](docs/linux-desktop.md)** | Linux Desktop users | Full setup and operations |
| **[`docs/FORK.md`](docs/FORK.md)** | Maintainers | Rebase, matrix changes, tests, publishing |

Upstream reference: [0xSero/codex-shim](https://github.com/0xSero/codex-shim).

---

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest tests/ -q
```

---

## License

MIT — see [`LICENSE`](LICENSE).

Codex Desktop is a trademark of OpenAI. **rabesss/codex-shim** is maintained independently and is **not affiliated** with OpenAI or 0xSero.