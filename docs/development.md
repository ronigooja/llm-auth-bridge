# Development

Python 3.12 is the supported runtime; app imports have no initialization side effects. Install and verify with the committed locks:

```sh
uv sync --frozen --extra test --extra browser --python 3.12
cd frontend
npm ci
npm test
npm run build
cd ..
uv run pytest
```

To enable real local synthetic browser tests, install Chromium (`uv run playwright install --with-deps chromium`) or set `BRIDGE_TEST_CHROMIUM` to a system Chromium. Test-only root launches disable the sandbox; production `run_login` requires it. Set `BRIDGE_TEST_GOST` to a checksum-verified GOST 3.3.1 release executable to run all three proxy protocol tests. Missing browser/GOST or frontend build causes the corresponding local acceptance tests to skip; CI explicitly provisions those prerequisites. No test contacts a provider account. Live test HTTP servers use loopback and synthetic data; no traces, HAR, video or screenshots are collected.

`tests/test_ui_live.py` exercises built UI -> real FastAPI -> serial synthetic worker -> human code -> synchronization -> refresh. Other suites cover migrations/rollback, wrong/missing keys, backup/restore, auth/CSRF/login concurrency, durable queue locks/leases, cancellation boundaries, human timeout, sync uncertainty and correction, adapter contracts, fresh-mail selection, TOTP, route isolation, and authenticated WebSocket logout revocation.

Use `LLM_AUTH_DB` and `LLM_AUTH_MASTER_KEY_FILE` pointing at temporary local paths for development. `python -m app.cli init` prompts for a password; never pass one on the command line. Set `LLM_AUTH_SECURE_COOKIE=false` only for local HTTP. Vite development requires an explicitly configured same-origin API proxy; the supported acceptance path builds assets and serves them through FastAPI.

## Collaboration and extensions

Main owns architecture, contracts, migrations, scheduling, integration and serial real-account acceptance. Per AGENTS.md, file-changing delegates use isolated worktrees under `$HOME/subagents/llm-auth-bridge/<task>` after a main commit. Bounded work uses gpt-6-luna at medium effort; UI, complex code and independent review use gpt-6.1-sol at medium effort. Each handoff includes its commit, changed files, pytest result and unresolved issues. Integrate sequentially and rerun affected checks.

Never read real `auth.txt` in an agent task. Use synthetic fixtures; credentials and browser/database/mail data stay out of Git. Real account logins are main-only and serial. Record unverified capabilities as unverified.

Browser adapters implement `run_login(account,target,control,saved_state)`, typed credential result/identity/expiry, and safe fixed error messages. Control checkpoints enforce cancellation/leases and manual pauses. Downstream adapters implement `sync_credential` with stable remote IDs, explicit routes, identity/type validation, and write-uncertainty classification. Unknown exceptions must preserve uncertainty. Future mailbox adapters need pinned public egress, redirect enforcement, baseline/freshness/ambiguity tests and their exact site contract before activation. Update English documentation for every interface change.
