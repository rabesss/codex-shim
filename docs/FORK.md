# Fork Maintenance

This repository is a Linux-focused fork of
[`0xSero/codex-shim`](https://github.com/0xSero/codex-shim) and the companion
adapter for
[`rabesss/codex-desktop-control`](https://github.com/rabesss/codex-desktop-control).

## Ownership Boundary

Keep changes in this repository when they concern:

- CLIProxyAPI discovery and route metadata;
- Codex Responses, streaming, compaction, image, or tool translation;
- namespace-tool flattening/restoration;
- credential resolution and loopback service behavior;
- generated catalog/config/profile helpers.

Keep Desktop picker, fork/resume payloads, Browser feature exposure, ASAR
patches, packaging, and installed-app verification in the companion Desktop
repository.

`patch-app` and `restore-app` remain for legacy overlay compatibility. Do not
expand them as the primary integration path.

## Upstream Sync

The expected remotes are:

```text
origin  https://github.com/0xSero/codex-shim.git
fork    https://github.com/rabesss/codex-shim.git
```

Before rebasing or merging upstream:

1. Review `git diff origin/main...main` and classify each fork-owned change.
2. Preserve loopback/Host-header security checks and credential behavior.
3. Re-run translation tests, especially streaming and namespace tools.
4. Re-run the cross-repository Desktop fork/resume/Browser smoke path.
5. Keep official OpenAI routing direct in the companion Desktop setup.

## Model Matrix Changes

CLIProxyAPI is the provider source of truth. Prefer live discovery. Bootstrap
rows and capability overrides are fallback metadata only and should contain no
provider endpoints beyond the local aggregator, no account identifiers, and no
credential values.

After matrix changes:

```bash
codex-shim desktop write-models --output /tmp/models.json
codex-shim --settings /tmp/models.json generate
codex-shim --settings /tmp/models.json list
```

Inspect generated JSON for duplicate slugs, unsupported capabilities, personal
data, and secret-shaped fields before publishing.

## Required Tests

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
python3 -m compileall -q codex_shim
git diff --check
```

For translation changes, include focused coverage for request history,
streaming deltas, terminal events, and returned tool-call shape. For Desktop
integration changes, also run the companion repository's custom-model feature
tests and installed routing verifier.

## Release Checklist

1. Confirm all tracked documentation uses the current companion repository and
   no removed branch or legacy Linux wrapper.
2. Confirm generated files, logs, auth data, request dumps, and local service
   files are untracked.
3. Scan tracked Markdown and fixtures for personal paths, account ids, tokens,
   and credential values.
4. Run the full test suite and `git diff --check`.
5. Commit the shim independently and record the companion Desktop commit used
   for integration validation.
6. Push only a clean, reviewed `main` commit to the fork remote.

## Documentation Map

- [`../README.md`](../README.md): public architecture, setup, and limitations.
- [`linux-desktop.md`](linux-desktop.md): integrated Desktop setup and smoke
  tests.
- [`AUTO_ROUTER.md`](AUTO_ROUTER.md): optional classifier/router behavior.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md): contributor workflow and reports.
