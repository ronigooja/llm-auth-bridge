# Development

Python 3.12 is the supported runtime. App imports are side-effect free; schema changes run explicitly through the CLI. Use the committed locks and run executable checks on GitHub-hosted runners:

```sh
uv sync --frozen --extra test --extra browser --python 3.12
cd frontend && npm ci && npm test && npm run build
cd .. && uv run pytest
```

CI provisions Chromium and the checksum-verified GOST executable for browser and proxy coverage. To use a system browser, set `BRIDGE_TEST_CHROMIUM`; set `BRIDGE_TEST_GOST` to a checksum-verified GOST 3.3.1 executable for all proxy protocol tests. Synthetic suites use temporary databases, loopback servers, and synthetic accounts; they do not contact provider accounts. Tracing, HAR, video, and screenshots are disabled by default.

For local development, set `LLM_AUTH_DB` and `LLM_AUTH_MASTER_KEY_FILE` to temporary paths. `python -m app.cli init` prompts for a password; never put passwords in command arguments. Set `LLM_AUTH_SECURE_COOKIE=false` only for local HTTP. Vite development requires an explicitly configured same-origin API proxy; production acceptance serves the built assets through FastAPI.

See [AGENTS.md](../../AGENTS.md) for repository workflow, security, baseline, delegation, and handoff rules. Update the relevant English architecture or contract document whenever an interface changes. Runtime behavior is summarized in [architecture](../architecture/overview.md); HTTP and adapter contracts are under [contracts](../contracts/).
