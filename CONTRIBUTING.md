# Contributing to codex-shim

Issues and pull requests are welcome.

## Dev loop

```bash
git clone https://github.com/rabesss/codex-shim
cd codex-shim
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"

python3 -m pytest tests/ -q
python3 -m compileall codex_shim/ -q
```

CI runs the same commands on Python 3.11 and 3.12 via
`.github/workflows/ci.yml`. Match it locally before opening a PR.

## What kinds of changes are useful

- Translation fixes for tricky tool-call / reasoning streams, with a
  captured fixture under `tests/` proving the bug and the fix.
- New provider translations (e.g. a new chat-completions or
  Anthropic-shaped upstream). Add a test that exercises the new shape end
  to end through `ShimServer`, the way `test_server.py` does.
- Compatibility fixes for the companion
  [`codex-linux`](https://github.com/rabesss/codex-linux)
  integration when they belong at the catalog or wire-protocol boundary.
- Documentation backed by a specific Desktop, Codex CLI, and shim version.
  Picker, thread lifecycle, Browser exposure, and package patches belong in the
  companion Desktop repository.

## Code style

- Match the surrounding file. No new dependencies without a reason.
- Keep `codex_shim/server.py` translation behavior covered by tests in
  `tests/test_server.py` or `tests/test_translate.py` — tool-call shape
  bugs are easy to miss by eyeballing streams.
- Don't include API keys, ChatGPT access tokens, or `auth.json` contents
  in fixtures, logs, or test data. Use synthetic tokens (`"stub"`,
  `"secret"`) like the existing tests.

## Reporting bugs

Please include:

- Codex CLI version (`codex --version`) and `codex-desktop-linux`
  package/source commit.
- Linux distribution, desktop environment/window manager, and whether the
  app is launched from a native package, development build, or wrapper.
- Output of `codex-shim status` and the last ~80 lines of
  `.codex-shim/shim.log` with API keys redacted.
- Whether the model is a CLIProxyAPI/custom route or an optional passthrough.
- Minimal repro: the exact `codex-shim …` invocation and what you
  expected vs. what happened.
- For Desktop bugs, both repository commits and whether failure occurs on
  thread start, fork, `/goal`, resume, or tool dispatch.

## Security

Do not open public issues for security problems. Use GitHub's private security
reporting for this repository with a minimal, redacted reproduction.
