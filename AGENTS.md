# AGENTS.md

Guidance for AI coding agents and reviewers in **codex-shim** — a Linux-focused fork of
[`sybil-solutions/codex-shim`](https://github.com/sybil-solutions/codex-shim) that bridges Codex Desktop custom
rows to CLIProxyAPI. The PR review charter is in [`REVIEW.md`](REVIEW.md).

## Project

`codex-shim` exposes a loopback Codex-compatible Responses API and model catalog, then translates
requests to CLIProxyAPI-backed OpenAI-chat or Anthropic-compatible routes. Desktop picker/session
behavior lives in the companion repo [`rabesss/codex-desktop-linux`](https://github.com/rabesss/codex-desktop-linux).

## Architecture

- `codex_shim/server.py` — loopback HTTP service, request routing.
- `codex_shim/translate.py` — Responses ↔ provider protocol translation.
- `codex_shim/router.py` — model/provider routing and capability metadata.
- `codex_shim/catalog.py`, `codex_shim/settings.py`, `codex_shim/desktop_models.py` — catalog and config.
- `codex_shim/cli.py` — CLI entry (`codex-shim`, `generate`, `list`, `desktop write-models`).
- `docs/FORK.md` — fork maintenance and upstream sync rules.

## Conventions agents MUST follow

- Never log, print, or commit credentials, OAuth tokens, account identifiers, or full request dumps.
- Keep official OpenAI models on direct routing; custom rows use the shim only.
- Preserve loopback/Host-header security checks.
- Add or update tests under `tests/` for translation, streaming, and tool-call behavior changes.
- Keep fork-specific Desktop integration out of this repo — stage it in `codex-desktop-linux`.

## Review guidelines

- **P0** — credential or token exposure in code, logs, generated JSON, or errors.
- **P0** — routing first-party OpenAI traffic through the shim.
- **P1** — missing tests for changed translation/streaming/tool paths.
- **P1** — catalog rows with secrets, duplicate slugs, or unsupported capability flags.
