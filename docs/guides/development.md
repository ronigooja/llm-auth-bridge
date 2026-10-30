# Development

Python 3.12 is the supported runtime. App imports are side-effect free; schema changes run explicitly through the CLI. Use the committed locks; for a prepared checkout:

```sh
export UV_PROJECT_ENVIRONMENT="$HOME/environment/bridge-venv"
export UV_CACHE_DIR="$HOME/environment/uv-cache"
export PLAYWRIGHT_BROWSERS_PATH="$HOME/environment/playwright"
export npm_config_cache="$HOME/environment/npm-cache"
uv sync --frozen --extra test --extra browser --python 3.12
cd frontend && npm ci && npm test && npm run build
cd .. && uv run pytest
```

For local development, set `LLM_AUTH_DB` and `LLM_AUTH_MASTER_KEY_FILE` to temporary paths. `python -m app.cli init` prompts for a password; never put passwords in command arguments. Set `LLM_AUTH_SECURE_COOKIE=false` only for local HTTP. Vite development requires an explicitly configured same-origin API proxy; production acceptance serves the built assets through FastAPI.

See [AGENTS.md](../../AGENTS.md) for repository security and handoff rules. Update the relevant architecture or contract document whenever an interface changes. Runtime behavior is summarized in [architecture](../architecture/overview.md); HTTP and adapter contracts are under [contracts](../contracts/).

## Test boundaries

CI provisions Camoufox and its paired Firefox and the checksum-verified GOST executable for browser and proxy coverage. To use a system browser, set `BRIDGE_TEST_GOST` to a checksum-verified GOST 3.3.1 executable for all proxy protocol tests. Synthetic suites use temporary databases, loopback servers, and synthetic accounts; they do not contact provider accounts. Tracing, HAR, video, and screenshots are disabled by default. See the [roadmap](../roadmap.md) for acceptance status and remaining verification.


## CI entry points

- [Fast deployment gate](../../.github/workflows/fast-gate.yml) runs frontend
  tests/build, non-browser pytest, a synthetic Camoufox preflight and amd64
  app/worker startup checks in parallel. Every job must pass before publishing.
  Pushes to main, validation and deployment branches validate without publishing.
  Dispatch [deployment.yml](../../.github/workflows/deployment.yml) with
  `publish=true` to validate and publish SHA-tagged GHCR images and digest records.
- [Full pytest regression](../../.github/workflows/full-regression.yml) runs all
  synthetic pytest nightly, manually or on validation branches. It is independent
  of image publication. A release gate pass does not imply full regression passed.
- [Checks](../../.github/workflows/checks.yml) retains path-based frontend,
  browser preflight and multiarchitecture build checks. It does not run full pytest.
- [Native OAuth validation](../../.github/workflows/validation.yml) retains native
  CPA tests and upstream comparisons; bridge full pytest runs in Full pytest
  regression. Upstream failures remain failures even if focused diagnostics pass.
- [Account viewer regression](../../.github/workflows/novnc.yml) checks packaged
  noVNC behavior. Real accounts and physical client acceptance are separate.

When running release tests, the CI plugin bounds each test, including fixture
setup and teardown, to 90 seconds. GNU timeout bounds non-browser pytest to five
minutes, browser preflight to three minutes and full regression to 18 minutes,
then kills the process group after a short grace period. Step/job limits reserve
room to upload logs. Faulthandler emits diagnostics; it is not the timeout
mechanism. If the full suite cannot finish writing JUnit, CI creates an explicit
failed-process report. Interrupted or missing results never count as passed.

The fast gate targets 10–15 minutes with warm caches; cold container builds can
exceed that target and have a 20-minute job limit. uv/npm, Camoufox and pinned
GOST caches reuse dependencies, while Docker layer caches retain system/browser
installation layers. Browser OS packages are provisioned only for jobs needing
them. GOST is checksum-verified from its pinned GitHub release into a temporary
`/tmp/bridge-gost.*` directory, then installed under
`$HOME/environment/gost/3.3.1-linux-amd64`; temporary archives are removed.

When assessing coverage, inspect skipped tests and job conclusions. Retain the
source revision, run URL and conclusions with release records. Gate logs expire
after seven days; full regression logs and image digest records expire after 30
days. No image tarball is uploaded as an Actions artifact.
