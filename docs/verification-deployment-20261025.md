# Deployment and real-account verification, 2026-10-25

## Inputs and hosted validation

Deployed bridge revision: `65a8669a9307b29cee925e008efcb90bf3e41986`.
The input checkout had no uncommitted source changes. This revision adds the
`Deployment artifacts` workflow to application revision `79e2067`; it does not
change the application code from that revision.

[GitHub Actions run 40220196006](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40220196006)
completed successfully. The `validate` job ran on GitHub-hosted `ubuntu-24.04`
with Python 3.12 and Node 22.14.0. The `images` job used the native
`ubuntu-24.04-arm` runner. No compilation, image build, or automated test suite ran
on the controller. Loading CI images, service operation, database migration, and
serial real-account observation used the existing deployment host.

| Command / scope | Actual exit | Result |
| --- | --- | --- |
| `npm test --prefix frontend` | 0 | 38 tests passed across three files |
| `npm run build --prefix frontend` | 0 | TypeScript and production build passed |
| `uv run pytest -ra --junitxml=deployment-logs/pytest.xml` | 0 | 251 passed, one skipped, four warnings |
| `docker build --target app --label org.opencontainers.image.revision="$GITHUB_SHA" -t "llm-auth-bridge-app:$GITHUB_SHA" .` | 0 | Native ARM64 app image built |
| `docker build --target worker --label org.opencontainers.image.revision="$GITHUB_SHA" -t "llm-auth-bridge-worker:$GITHUB_SHA" .` | 0 | Native ARM64 worker image built |

The skipped test requires a separately configured disposable Voice acceptance
server. This run did not build or deploy the optional CPA native extension or
modify the deployed Voice gateway. The existing CPA target retains
`cpa-auth-files-v1`.

Validation evidence was downloaded to
`/tmp/bridge-real-login-20261025/validation/`; `validation.exit` is `0`.
The image archive and build logs are under
`/tmp/bridge-real-login-20261025/images/`; `build.exit` is `0`.
Run and job metadata are saved beside those directories as `run.json` and
`jobs.json`. These are controller evidence paths, not durable backup storage.
Hosted validation artifacts expire after seven days; deployment image artifacts
expire after two days.

The downloaded ZIP passed CRC verification. The exported image archive passed
SHA-256 verification:
`2faf5e05d141b9c4d7b0f53a25d719d69789e5779f7b846d81b764331df4e41b`.

## Deployment acceptance

The operator explicitly requested no backup. No pre-upgrade database backup or
additional rollback image tags were created. Existing unrelated backups and
images were not removed. Both services were idle before the upgrade.
Scheduled maintenance was temporarily disabled, both services were stopped,
and the new images were loaded and tagged for the existing Compose stack.
The offline `docker compose run --rm --no-deps app python -m app.cli migrate`
command exited `0`, migrating schema v1 to v2 using the existing encryption key.
`docker compose up -d --no-build --pull never --wait app worker` exited `0`.
The command transcript and actual exit statuses are saved at
`/tmp/bridge-real-login-20261025/deployment.log`.

Both services passed their health checks and `/readyz` returned HTTP 200.
All 17 application Python source hashes in each running container match the
reviewed checkout. Both running containers carry revision label `65a8669`.
The imported deployment image IDs reported by the deployment daemon are:

- App: `sha256:6a3c21491029283a219889f3db066bea7c3c2640f5e22b7c3cf7a7aecc37c9fa`.
- Worker: `sha256:3d40b0f30def6dd35accc8f1519da4d3b322e10d2152acba71a284babff1f5c6`.

The existing data volume, encryption key, account routes, target settings, and
private worker display were retained. The existing Voice gateway's container ID,
image ID, and start time were unchanged. Scheduled maintenance was restored to
its previous enabled setting after the first login attempt was cancelled.

## Real-account observation

The main operator initiated tasks serially through the authenticated application
API. No real `auth.txt` was read or copied. No credentials, OTPs, mailbox contents,
provider tokens, screenshots, or browser storage are included in this document
or Git. Browser tracing, HAR, and video remained disabled.

Task 7 used the existing stored account and account route. Headed Chromium
started with sandboxing enabled and reached the OpenAI authorization endpoint.
It displayed the Cloudflare security verification page before any email or
password form. After the bounded observation period, the adapter entered
`waiting_human`, and authenticated takeover remained available. The operator
requested cancellation: the task reached `cancelled`, and
`takeover_available` returned to `0`.

A subsequently supplied account and authenticated SOCKS5 route were stored through
the normal encrypted account API as a separate account. The supplied `socks5h`
URL was represented using the API's `socks5` server format and separate
credentials for the GOST connector. Task 8 reached the same Cloudflare security
verification page and paused in `waiting_human`. It had not reached email,
password, TOTP, consent, code exchange, or downstream synchronization at the time
of this record. Its continuation requires completion of the current challenge.
No automatic mailbox navigation occurred.

This observation establishes deployed browser startup, navigation to the provider,
manual pause behavior, and cancellation cleanup for task 7. It does not establish
successful login, credential validity, full proxy egress/DNS behavior, cross-target
session reuse, or downstream acceptance. Those capabilities remain unverified.
