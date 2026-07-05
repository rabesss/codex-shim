# REVIEW.md — codex-shim

Canonical PR review guide for this **Linux-focused fork** of
[`sybil-solutions/codex-shim`](https://github.com/sybil-solutions/codex-shim). Companion Desktop
integration lives in [`rabesss/codex-linux`](https://github.com/rabesss/codex-linux).

This fork no longer tracks the upstream project's full review-bot fleet. Configure
only the agents that actually review here:

| Reviewer | Config file it reads |
|----------|----------------------|
| OpenAI Codex (`chatgpt-codex-connector`) | `AGENTS.md` |

> Do not add CodeRabbit, Kilo, Greptile, or Qodo configs unless those bots are
> explicitly enabled for this repository.

## Load-bearing invariants

- **Official OpenAI/Codex models stay direct** (`model_provider = "openai"`). This shim is
  opt-in for custom rows only — never a hidden hop for first-party traffic.
- **Loopback security:** preserve Host-header and loopback binding checks; do not widen the
  service to LAN/WAN without an explicit threat model.
- **Credential hygiene:** no API keys, OAuth tokens, account IDs, or request dumps in logs,
  generated catalogs, committed JSON, or exception text. CLIProxyAPI owns provider creds.
- **Translation correctness:** streaming deltas, compaction, image payloads, namespace-tool
  flatten/restore, and returned tool-call shape must stay Codex-compatible.
- **Discovery vs bootstrap:** live CLIProxyAPI discovery is source of truth; bootstrap rows are
  fallback metadata only (no remote endpoints beyond the local aggregator).
- **Ownership boundary:** Desktop picker, ASAR patches, Browser feature exposure, packaging, and
  installed-app verification belong in `codex-desktop-linux`, not here.

## Severity calibration

- **Critical:** credential exposure, broken loopback security, official-model routing through the
  shim, catalog rows with secrets or personal data, translation regressions on streaming/tools.
- **Warning:** missing tests for changed translation paths, capability metadata drift, duplicate
  model slugs, unhandled provider errors surfaced as raw tracebacks.
- **Do not flag:** formatting-only diffs, upstream parity nits for removed Linux-incompatible
  features, speculative refactors outside the PR scope.

## Verification expectations

- Run `python3 -m pytest -q` and `python3 -m compileall -q codex_shim` for code changes.
- For catalog/matrix changes: `codex-shim desktop write-models`, `generate`, and `list` — inspect
  for duplicate slugs, unsupported capabilities, and secret-shaped fields before publishing.
- For Desktop integration changes, coordinate with `codex-desktop-linux` tests and installed
  routing verification.

## Agent-Maintained Review Memory
Agents that open or update PRs in this repository must keep this section current when review history shows a repeated pattern. Add dated bullets only for durable repo-specific lessons, not one-off PR commentary.

- 2026-07-05: Pullfrog GLM 5.2 config must stay isolated at `.github/pullfrog-opencode.json`. Do not reintroduce repo-root `opencode.json` for Pullfrog; Kilo Code Reviews may load it and fail model resolution.
