# codex-shim — Linux Codex Desktop CLIProxyAPI bridge

**Linux-only maintained fork** of [0xSero/codex-shim](https://github.com/0xSero/codex-shim) for [ilysenko/codex-desktop-linux](https://github.com/ilysenko/codex-desktop-linux): a Codex-compatible loopback Responses shim plus Linux overlay tooling. Custom model rows are backed by **CLIProxyAPI** discovery/bootstrap data so hosted providers, OAuth providers, local OpenAI-compatible routes, and CommandCode stay behind the CLIProxyAPI aggregator instead of becoming a second provider registry in this repo.

---

## Use case

| Situation | Where to go |
|-----------|-------------|
| You want upstream generic shim behavior, non-Linux desktop support, or platform theory | Clone **[0xSero/codex-shim](https://github.com/0xSero/codex-shim)**. |
| You run **Codex Desktop for Linux** from **[ilysenko/codex-desktop-linux](https://github.com/ilysenko/codex-desktop-linux)** (`/opt/codex-desktop`), use CLIProxyAPI for custom providers, and want **first-class custom models** in the picker with CLIProxyAPI-backed model metadata + `patch-app` | Use **this repository**. |

This README explains **what the fork is and how it differs from upstream**. It is not a shortened copy of the upstream mega-README.

---

## How this differs from `0xSero/main`

| Layer | Upstream (`origin/main`) | This fork (`main`) |
|-------|--------------------------|---------------------|
| Core engine | Responses translation, daemon, `generate` / `start` / `enable`, provider adapters, ChatGPT passthrough, Auto Router docs | **Same core where useful** — rebased from upstream, but platform launch/patch code is Linux-only. |
| Desktop matrix | You maintain `models.json` yourself | **`codex_shim/desktop_models.py`** + `codex-shim desktop write-models` → CLIProxyAPI discovery with a bootstrap fallback |
| Credentials | Standard `api_key` / env patterns | **`api_key_env`**, **`api_key_credential`** (systemd `LoadCredentialEncrypted=`), **`api_key_file`**; no silent Cursor fallback on empty key |
| Catalog / picker labels | Upstream display rules | **Route-first** `Provider / Model` `display_name`; provider labels from settings / route metadata; compaction / truncation limits from settings |
| Codex Desktop UI | Upstream platform-specific patching varies | **Linux `patch-app` / `restore-app`** for user-local overlay under `~/.local/share/codex-desktop-linux-overlay/`; multi-variant JS needles |
| User documentation | Full README + platform guides on upstream | **[`docs/linux-desktop.md`](docs/linux-desktop.md)** (operational manual); this README (fork identity only) |
| Maintainer documentation | Upstream contribution flow | **[`docs/FORK.md`](docs/FORK.md)** (delta, rebase, tests, publishing) |
| Rust rewrite decision | Compatibility bridge design and cutover gates | **[`docs/RUST_ADAPTER_DESIGN.md`](docs/RUST_ADAPTER_DESIGN.md)** |

---

## What this fork adds

Changes on this branch relative to **`origin/main`** (refresh with `git diff origin/main...HEAD` after rebase):

| Area | What shipped |
|------|----------------|
| **`codex_shim/desktop_models.py`** | New module: CLIProxyAPI-backed `models.json` payload (`desktop_models_payload`, `write_desktop_models`). |
| **CLI** | `codex-shim desktop write-models` (`--output`, `--no-commandcode`, `--no-cpa-oauth`); Linux-aware **`patch-app`** / **`restore-app`**; health check timeout 3s. |
| **`codex_shim/settings.py`** | Credential resolution order; `$CREDENTIALS_DIRECTORY` support; `auto_compact_token_limit`, `truncation_limit`. |
| **`codex_shim/catalog.py`** | Picker `display_name` + provider labels; reasoning summary defaults. |
| **`codex_shim/server.py`** | Clearer credential errors; versioned `/vN` base URL join. Provider-specific adapters stay in CLIProxyAPI. |
| **Tests** | `tests/test_settings_catalog.py` (CLIProxyAPI matrix, credentials, catalog, Linux bundle patch); upstream server/translation tests remain intact. |
| **Docs** | [`docs/linux-desktop.md`](docs/linux-desktop.md) — architecture, routing, credentials, capability policy, full `patch-app` procedure; [`docs/FORK.md`](docs/FORK.md) — maintainer playbook; [`docs/RUST_ADAPTER_DESIGN.md`](docs/RUST_ADAPTER_DESIGN.md) — Rust parity and rollout design. |

**Example matrix slugs:** `zai-coding-glm-5-1`, `opencode-go-deepseek-v4-pro`, `opencode-go-mimo-v2-5-pro`, `commandcode-deepseek-v4-pro`, `grok-composer-2-5-fast`.

---

## What we do not maintain here

- The **upstream long README** is not the face of this repository — generic install, subscription passthrough, Cursor Composer, Auto Router, non-Linux workflows, and platform theory stay on **[0xSero/codex-shim](https://github.com/0xSero/codex-shim)**.
- **Operational depth** (systemd units, overlay paths, troubleshooting, full `patch-app` steps, credential file layout) lives only in **[`docs/linux-desktop.md`](docs/linux-desktop.md)** — not duplicated below.

When you need upstream behavior or docs, use upstream; when you need Linux Desktop + CLIProxyAPI-backed custom models, use this fork and the linux-desktop guide.

---

## Quick start

```bash
git clone https://github.com/rabesss/codex-shim.git ~/codex-shim
cd ~/codex-shim
python3 -m pip install -e .

codex-shim desktop write-models --output ~/.codex-shim/models.json
codex-shim generate
codex-shim start
codex-shim enable    # writes an opt-in shim profile/wrapper; normal Codex stays direct
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
| **[`docs/RUST_ADAPTER_DESIGN.md`](docs/RUST_ADAPTER_DESIGN.md)** | Maintainers | Rust compatibility boundary, parity gates, rollout |

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

Codex Desktop is a trademark of OpenAI. This project is maintained independently and is **not affiliated** with OpenAI or 0xSero.
