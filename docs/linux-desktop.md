# Linux Desktop Integration

This guide connects
[`rabesss/codex-shim`](https://github.com/rabesss/codex-shim) to
[`rabesss/codex-desktop-control`](https://github.com/rabesss/codex-desktop-control).
The two repositories are designed as one custom-model stack with separate
ownership boundaries.

## Responsibilities

`codex-desktop-control` owns:

- the Linux Desktop package and app bundle patches;
- custom rows in the model picker;
- provider selection on new threads;
- provider/model/session preservation on fork, including `/goal`;
- dynamic tool refresh on resume;
- Linux Browser extension and native-host integration.

The maintained Browser path is the patched official Browser/Chrome plugin
surface plus the Linux Computer Use backend. It does not depend on Agent
Workspaces, a hidden workspace browser, or `agent-workspace-linux`.

`codex-shim` owns:

- CLIProxyAPI model discovery and Desktop catalog metadata;
- the loopback Codex Responses API;
- streaming, compaction, image, and tool translation;
- namespace-tool flattening and restoration for nested and flat MCP tools;
- native Responses output item type mapping for `apply_patch`, web search, and
  normal function calls;
- request-time credential and capability checks.

CLIProxyAPI owns provider routes and provider credentials. Official OpenAI/Codex
traffic bypasses both services.

## Prerequisites

- Python 3.11 or newer.
- CLIProxyAPI available on its configured loopback endpoint.
- A non-plaintext credential source for CLIProxyAPI discovery and requests.
- A `codex-desktop-control` build with `custom-model-catalog` enabled.

## Install The Shim

```bash
git clone https://github.com/rabesss/codex-shim.git
cd codex-shim
scripts/install-user.sh
codex-shim doctor
```

This installs an isolated user venv, a launcher under `~/.local/bin`, the
initial model matrix, and a systemd user service. The generated unit is
credential-neutral. Add any required `LoadCredentialEncrypted=` entries in a
systemd drop-in; do not add plaintext provider keys to the unit or repository.

Use `scripts/install-user.sh --no-service` if another supervisor will run the
server. Contributors can use an editable development venv instead.

Make the discovery credential available through your credential manager, then
generate a model matrix from live CLIProxyAPI discovery:

```bash
codex-shim desktop write-models --output ~/.codex-shim/models.json
```

The command writes credential names and route metadata, not secret values. If
the discovery credential is absent or CLIProxyAPI cannot be reached, it writes
the built-in bootstrap matrix instead. Regenerate after provider changes.

The same generated file controls the context footer and compaction timing in
Desktop. Live CLIProxyAPI fields such as `contextWindow`, `maxTokens`,
`autoCompactTokenLimit`, `truncationLimit`, `supportsTools`,
`supportsImageInputs`, and `supportsReasoning` are preserved when present. If a
route does not publish limits, the shim uses curated fallbacks for known
coding-plan aliases, including GLM 5.2 and MiniMax M3 long-context rows.

Default generated compaction starts at 82% of the model context window, while
history truncation is 22% capped at 128,000 tokens. To change those thresholds,
use a persistent per-model override:

```bash
codex-shim desktop compaction set "GLM 5.2" 165k --truncation 48k --all
systemctl --user restart codex-shim.service
codex-shim desktop compaction list
```

The model still advertises its full context window. Only automatic compaction
and truncation move earlier. The sibling `desktop-model-overrides.json` file is
reapplied whenever the matrix is regenerated. Clear the policy with:

```bash
codex-shim desktop compaction clear "GLM 5.2" --all
```

To change the global generated defaults instead, set ratios before
regenerating:

```bash
CODEX_SHIM_AUTO_COMPACT_RATIO=0.9 \
CODEX_SHIM_TRUNCATION_RATIO=0.1 \
codex-shim desktop write-models --output ~/.codex-shim/models.json
```

Explicit limits returned by CLIProxyAPI take precedence over these ratios, and
persisted per-model overrides are applied last.

Start the service:

```bash
codex-shim generate
codex-shim start
codex-shim status
codex-shim doctor --json
curl -s http://127.0.0.1:8765/health
```

`generate` and `start` write runtime files under
`${XDG_STATE_HOME:-~/.local/state}/codex-shim` by default, including the
generated catalog, generated Codex profile, PID file, shim log, and diagnostic
request dumps. Use `CODEX_SHIM_RUNTIME_DIR=/path/to/state` only for an explicit
development or test override.

For a durable service, run the same module from a user service and inject
credentials through an environment file with protected permissions or systemd
credentials. Do not put provider keys in the unit, model JSON, repo, or command
history.

## Build Desktop

In the companion Desktop checkout, enable the feature:

```json
{
  "enabled": [
    "custom-model-catalog"
  ]
}
```

Then rebuild and install:

```bash
make install-native
```

The supported path is a freshly generated package. `codex-shim patch-app` is a
legacy overlay command and should not be used to modify a package-owned app.

## Provider Configuration

The normal Codex provider stays first-party. Add the shim as a durable,
non-default provider so saved custom threads can resume after restart:

```toml
model_provider = "openai"

[model_providers.codex_shim]
name = "Codex Shim"
base_url = "http://127.0.0.1:8765/v1"
wire_api = "responses"
experimental_bearer_token = "dummy"
request_max_retries = 3
stream_max_retries = 3
stream_idle_timeout_ms = 600000
```

The dummy bearer value satisfies the Codex provider schema; it is not an
upstream provider credential. The shim resolves the selected route's real
credential at request time.

Do not set the global provider to `codex_shim` for the integrated picker. The
Desktop feature applies it only to selected custom rows.

## Credential Resolution

Model rows may use these sources:

| Field | Use |
|---|---|
| `api_key_credential` | Name of a systemd credential exposed through `$CREDENTIALS_DIRECTORY`. |
| `api_key_env` | Name of an environment variable containing the credential. |
| `api_key_file` | Path to a protected file containing the credential. |
| `api_key` | Literal value; supported for compatibility but not recommended. |

CLIProxyAPI-generated rows use `api_key_credential` for the internal
CLIProxyAPI key. Provider-specific keys remain in CLIProxyAPI.

## Catalog And Routing Checks

```bash
codex-shim list
curl -s http://127.0.0.1:8765/v1/models
curl -s http://127.0.0.1:8765/api/models
```

The Desktop catalog response should contain model and capability metadata but
no fields named like API keys, bearer tokens, authorization headers, or secret
values.

The routing contract is:

- official picker row: `model_provider=openai`, direct OpenAI/Codex route;
- custom picker row: session-scoped `model_provider=codex_shim`;
- custom picker row: session config also includes the generated
  `model_catalog_json`, so the selected row's context, compaction, truncation,
  image, reasoning, and tool metadata reaches Codex core;
- saved custom thread: durable `codex_shim` provider definition resolves after
  restart;
- shim route: selected model forwards to CLIProxyAPI or another explicitly
  configured compatible endpoint.

## Fork, Goal, And Resume Behavior

`/goal` can fork the active Desktop thread. Both repositories must be current:

- Desktop preserves the custom model, `modelProvider`, provider config, and
  dynamic tools in `thread/fork`.
- Desktop refreshes dynamic tools during resume.
- The shim preserves namespace-tool identity and native Responses tool item
  type through upstream translation.

If a custom thread works before `/goal` but its child stops reaching the shim,
the Desktop build is stale. If the child reaches the shim but Browser calls
return an unsupported tool name, check three things:

- the shim build includes native tool type mapping and flat MCP namespace
  restoration;
- the selected catalog row has `supports_tools: true`;
- the upstream provider actually emits compatible tool calls.

`web_search` and `computer_use` are native hosted tools. The shim does not
pretend they are normal BYOK functions unless a real executor exists. Use a
first-party row for native hosted web search or expose an executable MCP/tool
fallback.

## Validation

Run repository tests first:

```bash
# codex-shim
python3 -m pytest -q
python3 -m compileall -q codex_shim

# codex-desktop-control
node --test linux-features/custom-model-catalog/test.js
scripts/workstation/verify-policy.sh
scripts/workstation/verify-custom-model-mcp-routing.sh codex-app
```

Then verify through the installed Desktop UI:

1. The picker shows official and custom rows together.
2. An official row completes without a request appearing in shim logs.
3. A custom row completes through the shim.
4. Fork the custom thread, or create a goal, and complete another turn.
5. Restart Desktop and resume that custom thread.
6. With a tool-capable model, run one native Browser action.

## Troubleshooting

| Symptom | Check |
|---|---|
| Custom rows are absent | Verify `custom-model-catalog` was enabled and `/api/models` is reachable. |
| Shim reports no usable models | Regenerate `models.json` with the discovery credential available and verify request-time credentials. |
| Context footer shows the wrong model limit | Update codex-shim, rerun `desktop write-models` with the discovery credential available, restart the service, then inspect `/api/models` and the generated catalog for the new limits. |
| Desktop compacts too early or too late | Use `codex-shim desktop compaction set <slug-or-display-name> <tokens>`, restart the service, and verify with `desktop compaction list`. |
| Custom thread fails only after restart | Restore the durable non-default `[model_providers.codex_shim]` block. |
| `/goal` child no longer reaches the shim | Rebuild `codex-desktop-control` from current `main`; old fork payloads dropped provider state. |
| Browser tool is visible but returns `unsupported call` | Update both repos, confirm the row has `supports_tools: true`, and inspect returned `type`, `namespace`, and `name` fields. |
| Tool-heavy request routes to a cheap model that cannot call tools | Add `supports_tools` to router candidates and regenerate the catalog; missing values are treated conservatively. |
| CommandCode rows return `Unsupported model provider: commandcode` | Regenerate `models.json`; current shim also normalizes stale CommandCode rows to local CLIProxyAPI. |
| Browser opens a link in an uncontrollable new tab | Use explicit navigation for `target="_blank"` links; this is an extension-backend limitation. |
| Navigation is slow | Allow for the upstream site-status safety check before treating it as a hang. |

Full Browser backend constraints are maintained in the companion
[Browser Control guide](https://github.com/rabesss/codex-desktop-control/blob/main/docs/browser-control.md#backend-constraints).

## Optional Commands

`codex-shim enable`, `codex-shim codex`, and `codex-shim app` create or use an
opt-in shim profile. They are useful for isolated CLI testing, but the normal
integrated Desktop flow should keep official routing direct and select the shim
only for custom picker rows.

ChatGPT and Cursor passthrough support inherited from upstream is optional and
auth-gated. It is not required for the companion Desktop architecture.
