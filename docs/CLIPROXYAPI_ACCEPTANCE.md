# CLIProxyAPI-Backed Row Acceptance Plan

This plan defines the release gate for Codex Desktop custom rows that keep the
maintained request path:

```text
Codex Desktop -> codex_shim -> CLIProxyAPI -> selected provider route
```

It is not a direct CLIProxyAPI readiness plan. CLIProxyAPI stays the upstream
provider aggregator, OAuth owner, and local route owner. `codex-shim` owns the
Codex-specific Responses compatibility, catalog metadata, compaction handling,
tool-call normalization, and error normalization needed by Desktop custom rows.

## Non-Goals

- Do not patch CLIProxyAPI for Codex-specific behavior.
- Do not move Desktop custom rows to a top-level `cliproxyapi` provider as part
  of this plan.
- Do not route official OpenAI/Codex rows through `codex-shim`, CLIProxyAPI, or
  any local proxy.
- Do not publish raw request bodies, raw response bodies, screenshots with
  account strings, local filesystem paths, credentials, bearer tokens, cookies,
  OAuth material, or full model/provider account identifiers.
- Do not claim Browser, MCP, or full Desktop lifecycle readiness from endpoint
  probes alone.

## Required Setup

Use current `main` from both maintained repositories:

- `rabesss/codex-shim` for the loopback Responses compatibility service.
- `rabesss/codex-linux` for Desktop picker, provider-state, fork/resume, and
  Browser/Chrome integration.

Local validation only is expected for this plan. GitHub Actions may be
unavailable, so every acceptance record must name the local commands or manual
Desktop checks that were run.

Before testing, confirm these invariants:

- Codex Desktop's global provider remains `model_provider = "openai"`.
- Custom rows under test select the non-default `codex_shim` provider.
- The selected shim catalog rows resolve to CLIProxyAPI-backed routes.
- The shim health endpoint and model endpoints are reachable on loopback.
- Evidence capture is redacted before it leaves the local machine.

## Evidence Policy

Keep detailed evidence local. Public docs, PR descriptions, and commit messages
may include only sanitized summaries:

- case id;
- pass, fail, blocked, or not applicable;
- route family or generic capability class;
- normalized error category, if relevant;
- local validation command names without machine-specific paths;
- short failure explanation without payload excerpts.

Do not include raw payloads. When an endpoint trace is needed, store only a
redacted, minimized local artifact that removes prompts, tool arguments, tool
results, headers, credentials, account names, local paths, and complete model
provider identifiers.

## Acceptance Matrix

| ID | Case | Owner | Pass Criteria |
|---|---|---|---|
| CPA-SHIM-01 | Text non-streaming | `codex-shim` | A CLIProxyAPI-backed custom row returns a non-streaming Responses result with stable `id`, selected model slug, text output, finish state, and usage when available. Official rows remain absent from shim logs. |
| CPA-SHIM-02 | Text streaming | `codex-shim` | A streaming request emits parseable SSE events, includes text deltas in order, preserves the selected model identity, and emits a terminal event without stalling. |
| CPA-SHIM-03 | Compact non-streaming | `codex-shim` | `POST /v1/responses/compact` for a CLIProxyAPI-backed row completes as a non-streaming compact result or a documented normalized refusal that Desktop can handle. |
| CPA-SHIM-04 | Compact with `stream: true` | `codex-shim` | The shim accepts the Desktop compact request shape with `stream: true` and returns a Desktop-compatible compact response or stream. If the upstream route cannot stream compact output, the shim normalizes the behavior without exposing raw upstream errors to Desktop. |
| CPA-SHIM-05 | Tool-call creation | `codex-shim` | A tool-capable row can return a Responses tool-call item with stable call id, restored native item type where applicable, and preserved namespace/name identity for Browser, MCP, or normal function tools. |
| CPA-SHIM-06 | Tool-result continuation | `codex-shim` | A follow-up turn containing a tool result reaches the same route, preserves the prior call id linkage, and produces a final assistant result without losing tool namespace identity. |
| CPA-SHIM-07 | Auth failure normalization | `codex-shim` | Missing, expired, or rejected credentials are reported as a stable authorization error shape suitable for Desktop display, without leaking credential names, tokens, account strings, or raw upstream messages. |
| CPA-SHIM-08 | Unknown model normalization | `codex-shim` | Unknown or stale model slugs fail closed with a stable not-found or unsupported-model category, without falling back to an unrelated model or the official OpenAI provider. |
| CPA-SHIM-09 | Timeout/error normalization | `codex-shim` | Provider timeout, connection failure, malformed upstream response, and route errors are normalized into stable Desktop-compatible errors with no raw payload dump and no retry loop that blocks indefinitely. |
| CPA-SHIM-10 | Saved-thread resume/fork compatibility | `codex-linux` plus `codex-shim` | If Desktop lifecycle state is involved, a saved custom thread and a fork or `/goal` child preserve model slug, `modelProvider`, dynamic tools, and generated catalog metadata across restart and continuation. Endpoint-only shim probes are insufficient for this case. |

## Current Compact Finding

Redacted local validation on 2026-07-09 showed CPA-SHIM-03 and CPA-SHIM-04
passing through the maintained `codex_shim` route for `cline-pass-glm-5-2` and
`commandcode-qwen3-7-max`. Direct CLIProxyAPI bypass remains diagnostic and
blocked for compact `stream: true`; this result only records that the production
shim route is OK for the tested compact cases.

## Test Procedure

1. Record the `codex-shim` commit, companion `codex-linux` commit when used,
   Desktop package version when Desktop lifecycle is tested, and CLIProxyAPI
   version or service build identifier if available.
2. Confirm the shim catalog exposes the selected rows with clean
   `display_name`, `provider_display_name`, stable `slug`, context,
   compaction, image, reasoning, and tool capability metadata.
3. Run endpoint probes for CPA-SHIM-01 through CPA-SHIM-09 against the shim
   loopback endpoint, not directly against CLIProxyAPI.
4. Run Desktop lifecycle validation for CPA-SHIM-10 only in the companion
   Desktop environment. Keep screenshots, app logs, and thread artifacts local
   and redacted.
5. Record the outcome in a local acceptance report with one row per case.
6. Publish only the sanitized summary and validation command list.

## Local Validation Commands

Run the focused repository checks for a docs-only plan change:

```bash
git diff --check
```

If a spellchecker is available in the checkout or environment, run it on the
changed Markdown files. Examples:

```bash
codespell docs/CLIPROXYAPI_ACCEPTANCE.md README.md docs/FORK.md
```

Run a focused secret scan on the changed public docs before committing. A
minimal local grep-style scan is acceptable when the repository does not provide
a dedicated scanner:

```bash
rg -n -i "api[_-]?key|authorization|bearer|token|cookie|secret|oauth|account" \
  docs/CLIPROXYAPI_ACCEPTANCE.md README.md docs/FORK.md
```

Any hit must be reviewed. Generic policy wording such as `token` or `OAuth` may
remain only when it does not expose an actual credential, account, or local
machine value. Also inspect changed docs for absolute local path strings before
publishing.

## Release Decision

A CLIProxyAPI-backed row is accepted for the maintained shim path only when all
applicable matrix cases pass or are explicitly marked not applicable with a
reason. Any failure in compact handling, tool-result continuation, error
normalization, or Desktop lifecycle preservation blocks release for the affected
row family.

Passing this plan means the `codex_shim` path is acceptable for the tested
CLIProxyAPI-backed rows. It does not mean direct `cliproxyapi` provider rows
are ready, and it does not justify changing first-party OpenAI routing.
