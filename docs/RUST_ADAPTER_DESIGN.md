# Rust CLIProxyAPI Adapter Design

## Status

Design only. The Python implementation remains the reference and production
path. Do not cut over, replace the service, or change the normal Codex launcher
until the parity and live-smoke gates below pass.

## Objective

Build a strict Codex compatibility bridge over CLIProxyAPI:

- CLIProxyAPI owns provider, OAuth, hosted-model, and local-model discovery.
- The adapter owns Codex request/response translation and catalog metadata.
- Official OpenAI/Codex traffic stays direct and outside this service.
- Custom routing remains opt-in through the separate shim launcher/profile.

The Rust target must not become another provider registry.

## Reference Contract

The current Python service and its tests define behavior. Freeze reference
vectors before implementing Rust for:

- CLIProxyAPI model discovery and route-first labels.
- Capability overrides for image input, tools, reasoning, and streaming.
- `/health`, `/v1/models`, `/v1/responses`, `/v1/responses/compact`, and
  `/v1/chat/completions`.
- Streaming SSE event ordering, terminal events, usage, and error shapes.
- Function-call and function-result translation.
- Image and visual-feedback translation.
- Context, output, compaction, and truncation catalog metadata.
- Loopback Host validation and DNS-rebinding rejection.

Reference fixtures should be generated from sanitized requests and responses;
they must not contain credentials, personal paths, or account data.

## Proposed Components

Use one Cargo workspace with narrowly scoped crates:

| Crate | Responsibility |
|-------|----------------|
| `codex-adapter-core` | Config, model/capability types, catalog generation, translation, normalized errors |
| `codex-adapter-http` | Loopback HTTP/SSE server, Host guard, request limits, graceful shutdown |
| `codex-adapter-cli` | `generate`, `list`, `serve`, `check`, and parity-vector commands |
| `codex-adapter-tests` | Golden vectors and black-box parity harness |

Recommended foundations are `tokio`, `axum`, `reqwest`, `serde`,
`serde_json`, `toml`, `thiserror`, and `tracing`. Avoid provider SDKs: the only
custom-model upstream contract is CLIProxyAPI's OpenAI-compatible API.

## Data Flow

1. Load adapter settings and capability overrides.
2. Resolve only the CLIProxyAPI internal credential from environment or a
   systemd credential file.
3. Read CLIProxyAPI `/v1/models` and normalize stable route identities.
4. Merge user overrides by route/model identity.
5. Generate the Codex catalog and reject duplicate slugs.
6. Accept Codex-compatible requests on loopback.
7. Validate requested capabilities before forwarding.
8. Translate the request to CLIProxyAPI's OpenAI-compatible shape.
9. Translate normal or streaming output back to the Codex contract.

Model discovery failure may use an explicitly configured bootstrap snapshot,
but stale rows must be marked and must not silently gain capabilities.

## Capability Policy

Capabilities default closed when discovery does not prove them:

| Capability | Default | Adapter behavior when disabled |
|------------|---------|--------------------------------|
| Text input | Enabled | Reject model if absent |
| Image input | Disabled | Reject image-bearing requests before forwarding |
| Tools/functions | Disabled | Reject tool-bearing requests before forwarding |
| Reasoning | Disabled | Do not advertise or synthesize reasoning summaries |
| Streaming | Disabled | Use non-streaming upstream mode or reject streaming |

Overrides may enable a capability only after a live route smoke has passed.
Catalog flags and runtime enforcement must use the same resolved capability
object so UI metadata cannot drift from request behavior.

## Configuration

Keep configuration provider-neutral:

```toml
[cliproxyapi]
base_url = "http://127.0.0.1:8317/v1"
api_key_credential = "CLIPROXY_INTERNAL_API_KEY"

[[models]]
route = "opencode-go"
model = "deepseek-v4-pro"
display_name = "CLIProxyAPI / OpenCode Go / DeepSeek V4 Pro"
supports_images = false
supports_tools = true
supports_reasoning = true
supports_streaming = true
context_window = 200000
max_output_tokens = 32000
```

Do not add provider endpoints or provider keys here. Provider ownership and
authentication remain in CLIProxyAPI.

## Security Boundary

- Bind to loopback by default; non-loopback binding requires an explicit flag.
- Enforce the Python Host allowlist behavior before routing any endpoint.
- Apply request-body, response-body, SSE-line, timeout, and concurrency limits.
- Read secrets from environment or systemd credentials; never serialize them.
- Redact authorization headers, request bodies, and upstream error bodies from
  default logs.
- Do not read or mutate global `~/.codex/config.toml` from the server.
- Keep wrapper/profile generation in explicit CLI commands.

## Compatibility Details

- Preserve Codex response item IDs, call IDs, ordering, and terminal status.
- Preserve usage fields when CLIProxyAPI provides them; use `null` rather than
  invented values when it does not.
- Preserve assistant reasoning separately from user-visible output.
- Normalize provider errors to stable HTTP status and Codex error payloads
  without hiding the route that failed.
- Treat cancellation and client disconnect as upstream cancellation signals.
- Use bounded buffers for streaming translation; do not accumulate a complete
  response before emitting deltas.

## Parity Gates

Rust is not eligible for opt-in use until all gates pass:

1. The Python suite remains green and frozen reference vectors are committed.
2. Rust unit and property tests pass for catalog and translation logic.
3. Every reference vector produces semantically identical JSON/SSE output.
4. Catalog generation is deterministic and matches Python slug, label,
   capability, context, and compaction fields.
5. Black-box tests run both servers against the same fake CLIProxyAPI.
6. Live read-only discovery matches the active CLIProxyAPI model set.
7. One text, tool, reasoning, streaming, image-capable, and image-disabled route
   passes live smoke checks.
8. DNS-rebinding, malformed JSON, oversized payload, timeout, and cancellation
   tests pass.
9. Normal `codex` and the normal Desktop launcher still use direct `openai`.

## Rollout

1. Keep Python as the installed service.
2. Run Rust in shadow mode on a separate loopback port with synthetic traffic.
3. Add an explicit development launcher that targets Rust; do not change global
   Codex config.
4. Compare catalog and response traces with secrets and content redacted.
5. Permit an opt-in custom wrapper only after all parity gates pass.
6. Retain the Python service and wrapper as the immediate rollback path for at
   least one release cycle.

No live in-app mode toggle is part of this design. A future Desktop mode
indicator may select the opt-in wrapper only through a restart-required flow.

## Cutover Criteria

Cutover requires evidence, not implementation completeness:

- Zero known semantic parity failures.
- No unsupported capability advertised by the catalog.
- Equal or better failure isolation under upstream disconnects and malformed
  streams.
- Documented package, service, wrapper, migration, and rollback procedures.
- A clean public review confirming no provider registry or plaintext-secret
  handling was introduced.

