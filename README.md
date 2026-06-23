# codex-shim

`codex-shim` is a Linux-focused Codex Responses compatibility service for
custom models. It exposes a loopback Codex-compatible API and model catalog,
then translates requests to CLIProxyAPI-backed OpenAI-chat or
Anthropic-compatible routes.

This is a maintained fork of
[`sybil-solutions/codex-shim`](https://github.com/sybil-solutions/codex-shim). Generic and
non-Linux workflows remain upstream.

## Companion Repository

The supported Desktop integration is split between two repositories:

| Repository | Responsibility |
|---|---|
| [`rabesss/codex-linux`](https://github.com/rabesss/codex-linux) | Builds Codex Desktop for Linux, merges custom rows into the picker, preserves custom provider state across start/fork/resume, and exposes Linux Browser tooling. |
| [`rabesss/codex-shim`](https://github.com/rabesss/codex-shim) | Discovers CLIProxyAPI models, serves catalog metadata, and translates Codex Responses, compaction, images, streaming, and tool calls. |

Use current `main` from both repositories. Updating only one side can leave the
picker functional while `/goal`, thread forks, resumes, or Browser tool calls
still fail.

Official OpenAI/Codex models must remain direct on
`model_provider = "openai"`. This shim is an opt-in provider for custom rows; it
must not become a hidden route for first-party traffic.

Browser tools for custom rows use the companion Desktop repo's patched official
Browser/Chrome plugin surface and maintained Linux Computer Use backend. They
do not require Agent Workspaces, a hidden workspace browser, or
`agent-workspace-linux`.

## Architecture

```text
Codex Desktop custom row
  -> codex_shim provider at 127.0.0.1:8765
  -> Responses/catalog/tool compatibility
  -> CLIProxyAPI at 127.0.0.1:8317
  -> selected provider route
```

CLIProxyAPI owns provider endpoints, OAuth sessions, local model routes, and
provider credentials. This repository owns only the Codex compatibility layer
and Codex-specific capability metadata.

## What This Fork Adds

- CLIProxyAPI discovery with a deterministic bootstrap fallback.
- Clean Desktop display names, route provenance metadata, capabilities,
  context limits, and compaction metadata.
- `GET /api/models`, `GET /v1/models`, `POST /v1/responses`,
  `POST /v1/responses/compact`, and `POST /v1/chat/completions`.
- Streaming and non-streaming translation for OpenAI-chat and
  Anthropic-compatible providers.
- Image and visual tool-result translation.
- Namespace-tool flattening for upstream providers and namespace restoration
  on returned calls, required by Desktop Browser tools.
- Native Responses tool item mapping for returned calls. `apply_patch` returns
  as `custom_tool_call`, web-search calls return as `web_search_call`, and MCP
  calls preserve their Desktop namespace/name identity.
- Credential lookup through environment variables, files, and systemd
  credentials without serializing secret values into model catalogs.
- Linux profile/wrapper commands that keep the normal Codex configuration
  first-party by default.
- An optional Auto Router documented in [`docs/AUTO_ROUTER.md`](docs/AUTO_ROUTER.md).

## Quick Start

```bash
git clone https://github.com/rabesss/codex-shim.git
cd codex-shim
scripts/install-user.sh
codex-shim doctor
```

The installer creates an isolated venv, `~/.local/bin/codex-shim`, a generated
model matrix, and a credential-neutral `codex-shim.service`. It never writes
provider keys. Add encrypted systemd credentials or another protected
credential source separately, then regenerate the matrix after provider
changes so catalog rows do not become stale.

Use `scripts/install-user.sh --no-service` when another supervisor owns the
process. For development, use `python3 -m venv .venv` followed by
`python3 -m pip install -e ".[dev]"` instead.

Without a discovery credential, `desktop write-models` uses a built-in model
snapshot.
Generated runtime state lives in `${XDG_STATE_HOME:-~/.local/state}/codex-shim`
by default. Set `CODEX_SHIM_RUNTIME_DIR` only when you intentionally want an
alternate local state directory.

### Desktop Display Names

Desktop catalog rows keep the visible model label separate from route
provenance:

- `display_name` is the clean model name shown as the primary picker label.
- `provider_display_name` carries route metadata such as
  `CLIProxyAPI / CommandCode`.
- `slug` remains route-stable, even when it contains a legacy `cursor-` route
  prefix, because saved threads, compaction overrides, and CLIProxyAPI routing
  depend on it.

If a local route owner arrives as `cursor-nous-portal`, the shim keeps the
stable slug but presents the provider as `CLIProxyAPI / Nous Portal` and the
model as its own name, for example `Step 3.7 Flash:free`.

The Desktop-facing catalog should expose one visible row for each
`provider_display_name` plus `display_name` pair. If multiple route-stable
slugs collapse to the same clean provider/model label, the shim keeps the
first visible row and preserves routing distinctions in the slug and metadata.
Duplicate-looking selector rows are therefore catalog freshness issues, not a
reason to change the global Codex `model_provider` away from `openai`.

OpenAI Codex also has an official `--oss` mode for direct local Ollama and LM
Studio providers. That is separate from this CLIProxyAPI-backed Desktop
custom-endpoint stack. See OpenAI's
[OSS mode documentation](https://developers.openai.com/codex/config-advanced#oss-mode-local-providers)
when you want the direct local-provider path. Replacing this shim with the
official path requires an equivalent way to provide Desktop catalog metadata;
`--oss` by itself is documented for local providers, not remote CLIProxyAPI
route discovery.

### Context Windows And Compaction

Codex Desktop reads context-window and compaction thresholds from the shim's
catalog response. When `desktop write-models` can reach CLIProxyAPI, the shim
preserves model metadata such as `contextWindow`, `maxTokens`,
`autoCompactTokenLimit`, `truncationLimit`, tool support, image support, and
reasoning support. Those live fields take precedence over built-in fallbacks.

For discovered rows that do not report limits, this fork keeps curated
fallbacks for known coding-plan aliases. Current GLM 5.2 and MiniMax M3 aliases
are treated as 1,000,000-token context models with 131,072 output tokens, so
Desktop no longer falls back to the generic 128k display.

The default generated thresholds are:

- `auto_compact_token_limit`: 82% of the context window.
- `truncation_limit`: 22% of the context window, capped at 128,000 tokens.

For a persistent per-model policy, select by exact slug, upstream model id, or
display name. `--all` applies a shared display name to every matching route:

```bash
codex-shim desktop compaction set "GLM 5.2" 165k --truncation 48k --all
systemctl --user restart codex-shim.service

codex-shim desktop compaction list
codex-shim desktop compaction clear "GLM 5.2" --all
```

Overrides are stored next to `models.json` in
`desktop-model-overrides.json`, update the current matrix immediately, and are
reapplied after future `desktop write-models` runs. They change compaction and
history truncation without changing the advertised context window.

Set ratios before regenerating `models.json` when you want a different global
default instead:

```bash
CODEX_SHIM_AUTO_COMPACT_RATIO=0.9 \
CODEX_SHIM_TRUNCATION_RATIO=0.1 \
codex-shim desktop write-models --output ~/.codex-shim/models.json
```

Values are ratios from `0` to `1`; invalid values fall back to the defaults.
Explicit `autoCompactTokenLimit` or `truncationLimit` metadata from
CLIProxyAPI wins over the ratio. A persisted per-model override is applied
last.

`codex-shim enable` writes a separate opt-in profile and wrapper. It does not
need to change the top-level provider used by normal Codex. For the integrated
Desktop picker, follow [`docs/linux-desktop.md`](docs/linux-desktop.md).

## Tool Compatibility

Desktop can send namespace tools such as a Browser JavaScript executor. Most
OpenAI-chat and Anthropic-compatible APIs accept only ordinary function names.
The shim therefore:

1. flattens namespace plus child name into a callable upstream name;
2. applies the same mapping to function-call history;
3. preserves the original native tool type separately;
4. restores the original `namespace`, child `name`, and Responses output item
   type in returned calls.

This translation preserves dispatch identity; it does not make a provider that
lacks tool calling capable of using tools.

`web_search` and `computer_use` are native/server-side Codex tools. The shim no
longer advertises them to BYOK providers as ordinary fake functions, because
neither the shim nor Desktop can execute such function-call fallbacks. Use a
first-party model for native hosted web search, or expose a real MCP/function
tool with an executor.

## Security Boundary

- The server binds to loopback by default.
- Host-header checks reject untrusted hosts to reduce DNS-rebinding exposure.
- Browser picker mutations require an unguessable token embedded in the picker
  page, so another local-origin page cannot switch models with a blind POST.
- Catalog responses contain capability and route metadata, not provider keys.
- Provider credentials belong in CLIProxyAPI or a credential manager.
- Do not commit generated `models.json`, auth files, logs, request dumps, or
  service credential material.
- ChatGPT passthrough is separate, explicitly gated, and unnecessary for the
  recommended Desktop architecture because official rows already route direct.

## Known Constraints

- The integrated picker requires the `custom-model-catalog` feature from the
  companion Desktop repository.
- That feature passes this shim's generated native catalog into every custom
  thread. Picker labels alone do not configure Codex core; the catalog path is
  what applies each model's context, compaction, truncation, image, reasoning,
  and tool metadata at runtime.
- Saved custom threads require a durable, non-default `codex_shim` provider
  definition after Desktop restarts.
- Older Desktop builds could lose the provider during `thread/fork`, including
  `/goal`; rebuild the companion repo from current `main`.
- Older shim builds did not preserve namespace tool identity; update this repo
  if Browser tools return `unsupported call` despite being visible in Desktop.
- Older shim builds also returned every tool as a generic `function_call`;
  update if `apply_patch`, web search, or MCP connector calls fail even though
  the selected provider emitted the expected tool name.
- Stale `provider: commandcode` rows are normalized to the local CLIProxyAPI
  OpenAI-compatible route. Regenerate `models.json` after provider changes so
  capability metadata, especially `supports_tools`, stays accurate.
- Context windows and default compaction timing are generated into
  `models.json`. Regenerate after changing CLIProxyAPI metadata or global ratio
  settings; per-model `desktop compaction` overrides persist across regeneration.
- If Desktop shows `CLIProxyAPI / Cursor ...` as the primary picker label,
  update this repo, regenerate the Desktop catalog, restart the shim service,
  and restart Desktop. Current builds reserve route provenance for
  `provider_display_name`.
- If Desktop shows the same model twice under one provider, update this repo
  and inspect `/api/models` for duplicate `provider_display_name` plus
  `display_name` pairs. Current builds de-duplicate those visible rows before
  Desktop merges the selector catalog.
- Current companion Desktop builds also group the model submenu by
  `provider_display_name`, so provider separation should be fixed by improving
  catalog metadata rather than by prefixing `display_name`.
- CLIProxyAPI discovery falls back to a static snapshot when unavailable. That
  keeps setup deterministic but may show routes that need regeneration.
- Browser extension constraints such as invisible `target="_blank"` tabs,
  stale locators, and the reduced Playwright API remain upstream limitations.
  See the companion
  [Browser Control guide](https://github.com/rabesss/codex-linux/blob/main/docs/browser-control.md#backend-constraints).
- `codex-shim patch-app` and `restore-app` are retained for legacy overlay
  compatibility. The maintained integration is built by
  `codex-desktop-linux`; do not patch a package-owned app in place.

## Documentation

- [`docs/linux-desktop.md`](docs/linux-desktop.md): integrated setup, routing,
  credentials, validation, and troubleshooting.
- [`docs/AUTO_ROUTER.md`](docs/AUTO_ROUTER.md): optional task classifier and
  route selection.
- [`docs/FORK.md`](docs/FORK.md): fork ownership, upstream sync, and release
  checks.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): development and reporting guidance.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
python3 -m compileall -q codex_shim
```

## License

MIT. Codex Desktop is a product of OpenAI. This community project is not
affiliated with OpenAI or the upstream `codex-shim` maintainer.
