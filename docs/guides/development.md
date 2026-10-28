# Development

Python 3.12 is the supported runtime. App imports are side-effect free; schema changes run explicitly through the CLI. Use GitHub-hosted Linux runners for Linux builds/tests and GitHub-hosted macOS runners for Apple builds/tests. Prepare required environment files and tooling under `$HOME/environment` on the runner. Use the committed locks; for a prepared runner checkout:

```sh
export UV_PROJECT_ENVIRONMENT="$HOME/environment/bridge-venv"
export UV_CACHE_DIR="$HOME/environment/uv-cache"
export PLAYWRIGHT_BROWSERS_PATH="$HOME/environment/playwright"
export npm_config_cache="$HOME/environment/npm-cache"
uv sync --frozen --extra test --extra browser --python 3.12
cd frontend && npm ci && npm test && npm run build
cd .. && uv run pytest
```

CI provisions Camoufox and its paired Firefox and the checksum-verified GOST executable for browser and proxy coverage. To use a system browser, set `BRIDGE_TEST_GOST` to a checksum-verified GOST 3.3.1 executable for all proxy protocol tests. Synthetic suites use temporary databases, loopback servers, and synthetic accounts; they do not contact provider accounts. Tracing, HAR, video, and screenshots are disabled by default.

For local development, set `LLM_AUTH_DB` and `LLM_AUTH_MASTER_KEY_FILE` to temporary paths. `python -m app.cli init` prompts for a password; never put passwords in command arguments. Set `LLM_AUTH_SECURE_COOKIE=false` only for local HTTP. Vite development requires an explicitly configured same-origin API proxy; production acceptance serves the built assets through FastAPI.

See [AGENTS.md](../../AGENTS.md) for repository workflow, security, baseline, delegation, and handoff rules. Update the relevant English architecture or contract document whenever an interface changes. Runtime behavior is summarized in [architecture](../architecture/overview.md); HTTP and adapter contracts are under [contracts](../contracts/).


## CI entry points

- [Checks](../../.github/workflows/checks.yml) runs frontend tests/build, bounded
  Codex continuation preflight, full pytest, then app/worker multiarchitecture
  builds when the corresponding source paths change. Documentation-only pushes
  and pull requests are ignored. Frontend-only changes run the frontend checks;
  backend changes run the browser preflight and full pytest; image builds run
  only when application, frontend, deployment, or image/dependency files
  change. It supports manual dispatch: `gh workflow run checks.yml --ref
  <task-branch>`.
- [Native OAuth validation](../../.github/workflows/validation.yml) runs the bridge
  suite plus focused/full patched CPA Go tests, native compilation, and an
  untouched upstream comparison. Push to `validation/**` or dispatch manually.
  General Checks excludes those branches to avoid duplicate image builds.
- [Deployment artifacts](../../.github/workflows/deployment.yml) runs partitioned
  validation, selected headed acceptance and ARM64 image export. Its success is
  not a complete pytest verdict and does not deploy a running service.
- [Account viewer regression](../../.github/workflows/novnc.yml) checks packaged
  noVNC in Camoufox/Firefox, including synthetic Retina DPR 2 behavior.

Workflows are the source of exact provisioning steps, deadlines and artifact
names. Missing Camoufox, GOST or built frontend assets can skip corresponding
acceptance cases; inspect skip reasons before claiming coverage. Install the
pinned Camoufox browser with `uv run python -m camoufox fetch` on the runner
when needed. Production Camoufox runs headed in the desktop worker; test-only
headless fixtures may use Xvfb.

Collect the source revision, run URL, job outcomes and relevant artifacts before
their seven-day expiry. Inspect failed steps rather than reading successful logs.
The native workflow's full upstream failures remain failures even if an isolated
diagnostic passes; current conclusions are recorded in [the roadmap](../roadmap.md).
The [late-interrupt diagnostic](../../.github/workflows/upstream-late-interrupt.yml)
is restricted to `validation/upstream-late-interrupt`; it does not rerun full suites.
For disposable Voice server verification, use the guarded
[HTTP harness](../contracts/integrations/voice.md#disposable-synthetic-http-acceptance).

## Release gates and regression evidence

Deployment uses two independent conclusions. The fast gate is the blocking release check: frontend tests and build, non-browser pytest, a bounded synthetic Camoufox preflight, and app/worker image startup with non-root, seccomp and `/readyz` checks must all pass before an image is published. Each step has a short timeout and uploads its log and JUnit output on failure; a browser startup failure stops the release.

The complete pytest suite runs separately from [validation.yml](../../.github/workflows/validation.yml), on a nightly, manual, or validation branch dispatch. It has a per-test faulthandler deadline and a process-group hard timeout. A timeout is a failed run with the pytest log and JUnit report attached; an interrupted or missing run is never reported as passed. CI reuses the committed uv, npm and Camoufox caches and installs system browser packages only in the browser job.

Record each release's commit, fast-gate result, image digests, complete pytest state (`passed`, `failed`, `timed out`, or `not run`), online health result, and real-account status. Synthetic checks do not establish login, long-term renewal, or Voice audio acceptance.
