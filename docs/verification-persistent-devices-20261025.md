# Persistent account device deployment, 2026-10-25

## Deployed inputs

Application and image source revision:
`0b1c48e26c2722514d3b8786234b459cf2ac7a1f`.
The input checkout had no uncommitted source changes. Three implementation
sub-agents worked in isolated worktrees; main integrated their commits, added
schema/control contracts and reviewed lifecycle failure paths. No credentials,
real account databases, browser state, mailbox content or screenshots entered Git
or delegated tasks.

The implementation replaces per-task ephemeral browser contexts with separate,
encrypted Chromium device archives for each account. Tasks for the same account
restore its native user-data, including cookies, localStorage, IndexedDB and
preferences, across Voice/Codex tasks and worker restarts. Session cookies are
explicitly checkpointed inside the encrypted archive. Native sessionStorage
remains tab-scoped. Device separation does not imply separate physical hardware,
GPUs, fonts or fabricated fingerprints. The existing login task sequence remains
unchanged.

Profile v2 uses a 1760×900 viewport on a 1920×1080 screen. Proxy tasks resolve the
actual exit IP's IANA timezone through their configured route before navigation,
with bounded response size/deadline and cancellation checkpoints. Lookup failure
stops the task; it does not silently switch to direct routing or UTC.

## Collected hosted results

[Deployment artifacts run 40226773639](https://github.com/ronigooja/llm-auth-bridge/actions/runs/40226773639)
completed with **success**. The `validate` job used GitHub-hosted `ubuntu-24.04`
with Python 3.12, Node 22.14.0, uv 0.8.22 and Playwright 1.56.0. The `images` job
built and exercised native ARM64 images on `ubuntu-24.04-arm`.

| Exact command / scope | Exit | Result |
| --- | --- | --- |
| `npm test --prefix frontend` | 0 | 38 tests passed across three files |
| `npm run build --prefix frontend` | 0 | TypeScript and production build succeeded |
| `xvfb-run -a -s "-screen 0 1920x1080x24" uv run pytest -ra --junitxml=deployment-logs/pytest.xml` | 0 | 410 passed, one skipped, four warnings; 181.93 seconds |
| `docker build --target app --label org.opencontainers.image.revision="$GITHUB_SHA" -t "llm-auth-bridge-app:$GITHUB_SHA" .` | 0 | Native ARM64 app image |
| `docker build --target worker --label org.opencontainers.image.revision="$GITHUB_SHA" -t "llm-auth-bridge-worker:$GITHUB_SHA" .` | 0 | Native ARM64 worker image |
| Worker: `python -m pytest -v -s -p no:cacheprovider /acceptance/tests/test_browser_live.py -k headed_native_device` | 0 | One passed, 30 deselected; 2.38 seconds |

The worker test ran in the actual new image as UID/GID 10001, with the production
seccomp policy, no-new-privileges, sandbox-enabled headed Chromium, 1 GiB shared
memory, and private `/tmp` tmpfs. It verified native storage through a complete
in-memory AES-GCM archive roundtrip, removal of the first plaintext directory,
restoration to a different directory, and another account's storage isolation.
A separate worker assertion confirmed the IANA timezone database is available.
The only full-suite skip requires an explicitly configured disposable Voice
acceptance server; no such server was provisioned.

Actual ARM64 browser geometry was:

- Inner viewport: 1760×900, DPR 1.
- Outer window: 1768×1031.
- Screen and available screen: 1920×1080.

The initial 1760×960 viewport failed the full-window-fit assertion: its outer
height was 1091, exceeding 1080. The final implementation reduces viewport height
rather than weakening the fit check. An earlier run also identified three
synthetic legacy-profile fixture INSERT errors; explicit column names corrected
those fixtures. The final run includes these fixes.

No compilation, image build or automated test suite ran on the controller.
Controller work consisted of source/static checks, orchestration, artifact
collection, loading CI images and operating the authorized deployment.

## Artifacts and deployment

Controller evidence root: `/tmp/bridge-device-validation-20261025/`.
`run.json`, `jobs.json` and `artifacts.json` record hosted run/job/source metadata.
`validation/validation.log`, `validation/validation.exit` and
`validation/pytest.xml` contain full validation evidence; the exit file is `0`.
`images/build.log` and `images/build.exit` include exact image and container
acceptance commands/results; the exit file is `0`. Hosted validation artifacts
are retained seven days, image artifacts two days. Controller `/tmp` is an
operational evidence location, not durable backup storage.

The downloaded image ZIP passed CRC validation and the image archive passed its
SHA-256 check:
`fd2ccfece012e4c43ac1bba29e2f06d0610ffb14eaffd4645900447c4ca1cac9`.

The operator explicitly requested no backups. No database backup or additional
rollback image tags were created. Existing unrelated resources were not deleted.
There were no active tasks at deployment. Scheduled maintenance was temporarily
disabled, then the following operations completed with actual exit status `0`:

```sh
docker compose stop app worker
docker tag llm-auth-bridge-app:0b1c48e26c2722514d3b8786234b459cf2ac7a1f llm-auth-bridge-app:latest
docker tag llm-auth-bridge-worker:0b1c48e26c2722514d3b8786234b459cf2ac7a1f llm-auth-bridge-worker:latest
docker compose run --rm --no-deps app python -m app.cli migrate
docker compose up -d --no-build --pull never --wait app worker
```

The offline migration moved schema v2 to v3 using the existing encryption key.
Both containers carry the deployed revision label and passed health checks;
`/readyz` returned HTTP 200. All 19 application source hashes in each container
match the reviewed checkout. Scheduled maintenance was restored to its previous
enabled state. The existing account data, proxy/target configuration, volume and
Voice gateway were retained; the gateway container/image/start time did not
change.

Deployment daemon image IDs:

- App: `sha256:6bb945b74b703d103b3d8aea93cb3993326bab2edf6a0e1d1b0e8ff872992686`.
- Worker: `sha256:be213a2e6724ebaa614ee5385db91fd4cef621dd085ca64f26eeed2e6366b872`.

`deployment.log` records commands and actual exit statuses.
`containers-after.json`, `runtime-after.json` and `source-verification.json`
record the post-deployment checks.

## Remaining acceptance boundary

Synthetic acceptance establishes device persistence, encrypted archive isolation,
window fit and the timezone lookup contract. It does not establish successful
provider login, the supplied proxy's live geolocation, cross-target provider
session acceptance, or the cause of the earlier ChatGPT email-stage error. No
new real-account login was initiated as part of this deployment. Those outcomes
remain unverified and require serial checks using the account's existing device.
A hard process/container crash before archiving can lose changes from the current
task; previously committed device data remains available.
