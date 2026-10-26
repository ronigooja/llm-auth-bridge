# Branch audit and cleanup — 2026-10-26

## Baseline and scope

The user authorized auditing missing changes, preserving unfinished work, cleaning integrated branches and worktrees, and establishing a fresh-main workflow. The fetched baseline was `f85bfe56e39003bcb3ff4f0d99474817569bc33c`; the controller main worktree was clean and matched origin/main. No application behavior was changed by this maintenance task.

The initial inventory contained 43 local branches (including main), 15 remote branches (including main), and 27 worktree registrations. GitHub's default branch incorrectly pointed to `validation/native-oauth-browser-identity`. It was changed to `main`, and origin/HEAD was refreshed. Main has no configured branch protection; the documented merge process is not a server-enforced gate.

## Missing-change review

All 42 old local branches and all 14 remote task branches were checked with commit ancestry and `git cherry origin/main <branch>`. All changes were accounted for by ancestry or patch equivalence except two commits on `fix/codex-session-continuation`: `50f03185` and `5e9ed563`.

Those consecutive commits temporarily changed and then restored application chooser detection. Their combined application diff is empty. Their combined test diff is exactly the test diff in main commit `4428d7f`, as verified by comparing the patches. The current main still contains the navigation and diagnostics changes. There is no missing committed feature to cherry-pick from the audited branches. This does not prove every historical task fetched the latest remote before starting.

## Preserved unfinished work

`/root/subagents/llm-auth-bridge/simplify-account-window` remains untouched, detached at `399ef793d5c2d6cfb877b2883abb3a28b046265b` (already an ancestor of main). It has uncommitted modifications to:

- `app/main.py`
- `frontend/src/main.tsx`
- `tests/test_api.py`
- `docs/ui-guidelines.md`

These changes add an explicit saved-credential reveal API and form action. They were reviewed for identification only, have not been validated or integrated, and require a separate feature review against the latest main. No credential values, browser data, or runtime files were copied into this report or the archive tags. The worktree base has the recovery tag `archive/20261026/worktree/simplify-account-window-base`; that tag does not contain the uncommitted modifications.

## Cleanup and recovery

Before deletion, all 56 old branch tips and the preserved worktree base were tagged and pushed to origin (57 tags). Local branch tips use `archive/20261026/local/<old-name>`; remote branch tips use `archive/20261026/remote/<old-name>`. These tags preserve the original commits, including commits integrated under different hashes. Seven clean worktrees were removed without force; 18 stale registrations for missing directories were pruned. The dirty worktree was retained. All 42 old local task branches and 14 remote task branches were deleted. Remote deletion used an atomic push with expected-tip leases to reject concurrent branch updates.

To inspect an old tip, run `git show archive/20261026/remote/<old-name>`. To restore it for investigation, fetch the archive tag and create a new branch, for example:

```sh
git fetch origin --tags
git switch -c investigate-old-release archive/20261026/remote/deployment/account-window-release
```

Use a new branch from the latest origin/main for implementation; the restored branch is for historical comparison.

## Archive inventory

Each row records the exact tip before deletion. The tag prefix is `archive/20261026/`; main was retained.

| Original branch | Commit | Archive tag suffix |
| --- | --- | --- |
| `agent/backup-restore` | `feaca567479fc7ea088a224a308ea9586ffec44d` | `local/agent/backup-restore` |
| `agent/bridge-native-oauth` | `1943d1a17f984edeb7be0702f4d5d9ed201e491b` | `local/agent/bridge-native-oauth` |
| `agent/browser-identity` | `5a26500a1a9e89e447b948af9feac6770ee49431` | `local/agent/browser-identity` |
| `agent/ci-validation` | `095fb8c7bf4f40600edf895c28b96d3664c313ec` | `local/agent/ci-validation` |
| `agent/final-review` | `9b05c6f2e70821c76ad7b66d3ee701226fab801e` | `local/agent/final-review` |
| `agent/integration-review` | `d7907c2cdf3395e71bcb227a8d90b2dee033a77e` | `local/agent/integration-review` |
| `agent/ui-docs` | `e661094becd1b8e4e4e45cedbe343eebe3272889` | `local/agent/ui-docs` |
| `artifacts/novnc-app` | `44e5262a801a0bc1c975d1777760313a3807c898` | `local/artifacts/novnc-app` |
| `artifacts/novnc-worker` | `2cfc3c452f38697c9dfae82ca443df983c06ce64` | `local/artifacts/novnc-worker` |
| `dedupe-remote-sync` | `fc52a140098cd8ddc8af2510d32ac548d07aa235` | `local/dedupe-remote-sync` |
| `deployment/account-window-release` | `2f720c0e085ba2da8aa94bbb5841fe642bd806a0` | `local/deployment/account-window-release` |
| `deployment/adaptive-account-viewer` | `f85bfe56e39003bcb3ff4f0d99474817569bc33c` | `local/deployment/adaptive-account-viewer` |
| `deployment/browser-fill-desktop` | `6309bd14b317013c32821140f750c4a342ef4a2d` | `local/deployment/browser-fill-desktop` |
| `deployment/novnc-cookie-context` | `0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92` | `local/deployment/novnc-cookie-context` |
| `feature/browser-monitor` | `f2ed8ee7cd68719a99c53eb9186bbae9c24ca125` | `local/feature/browser-monitor` |
| `feature/ci-dependency-cache` | `b7fa5c5ff9c5072d69e56d8d63e1ee86f6062406` | `local/feature/ci-dependency-cache` |
| `feature/ci-layer-cache` | `4533068313322912ec5eaa33b7a401350b29ebf3` | `local/feature/ci-layer-cache` |
| `feature/login-workflow` | `832265b5a9c58392ce65aa3684b681e142f28002` | `local/feature/login-workflow` |
| `feature/login-workflow-optional` | `d5d1e042a6a2e43f0c383bf6c7a6ff5094a91eb9` | `local/feature/login-workflow-optional` |
| `feature/login-workflow-ui` | `eba70ee1ccc283995d5afab7177b0118c10887f2` | `local/feature/login-workflow-ui` |
| `feature/two-login-actions` | `4cfc8e97c8524d20fa1069bfe6508ab4d3605f02` | `local/feature/two-login-actions` |
| `fix/codex-session-continuation` | `c4c48c87ef92e92fc1c8912ce6087b64e61f26c1` | `local/fix/codex-session-continuation` |
| `fix/login-blank` | `3e4b0e8cd99b99b7306a988ae80cba5d737b5ec1` | `local/fix/login-blank` |
| `fix/login-stage-mismatch` | `d757df00be0ec0916e03fef2619a74f9b751fa86` | `local/fix/login-stage-mismatch` |
| `fix/novnc-cookie-context` | `0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92` | `local/fix/novnc-cookie-context` |
| `fix/password-transition` | `67b0e5afca7e6807ebbaee3b7ae75768e8557175` | `local/fix/password-transition` |
| `generic-code-contract` | `7a05f8e452c322adfe149d90e83ca03a3dc0637e` | `local/generic-code-contract` |
| `impl/device-storage` | `deea6018711803d00e2eb1cbc9358e95784a449a` | `local/impl/device-storage` |
| `impl/persistent-browser` | `e75aa787e62497100fe193c0db6c60a60cc62c90` | `local/impl/persistent-browser` |
| `impl/profile-timezone` | `5d9d6e09db1dbaa7df0d277bb3c5f4d7248da637` | `local/impl/profile-timezone` |
| `implementation/browser` | `5148ce41e9bf6f4bfe41c267993a6ce41fdf7667` | `local/implementation/browser` |
| `implementation/integrations` | `b05ac69064cb9deb057ed2b4b44015b600dd0697` | `local/implementation/integrations` |
| `implementation/proxy-tests` | `745ef8721c80cebaa150c55fc410730d1f63e722` | `local/implementation/proxy-tests` |
| `implementation/ui` | `dc8e33b4617f2fbbba640bff49d0141cca9b372b` | `local/implementation/ui` |
| `integration/dynamic-auth` | `f87974c290a21101b48aa7e4d0af6f4cb6eb8198` | `local/integration/dynamic-auth` |
| `review/login-takeover` | `d069a65d0cd425f704dbf1a3a81eeced8b295d6a` | `local/review/login-takeover` |
| `takeover-popup` | `1889e2d3d130c1b0eabd069d149f505b977556ac` | `local/takeover-popup` |
| `voice-contract-audit` | `199ead5699cd74d6be451e125f9f5e106ddec063` | `local/voice-contract-audit` |
| `voice-deploy` | `7ce2199edd2c4628976c2a1783a1d6067101da9b` | `local/voice-deploy` |
| `voice-gateway-compat` | `2bd0b3b5286b4b2074d369b5d493bc2d98d93fe7` | `local/voice-gateway-compat` |
| `voice-review` | `51328709408b50b31ea8275b98c49d55f9d728a3` | `local/voice-review` |
| `voice-runtime` | `51328709408b50b31ea8275b98c49d55f9d728a3` | `local/voice-runtime` |
| `origin/artifacts/novnc-app` | `44e5262a801a0bc1c975d1777760313a3807c898` | `remote/artifacts/novnc-app` |
| `origin/artifacts/novnc-worker` | `2cfc3c452f38697c9dfae82ca443df983c06ce64` | `remote/artifacts/novnc-worker` |
| `origin/deployment/account-window-release` | `dec10de4a5c7a1162fffdcea20a325f5c938c3a2` | `remote/deployment/account-window-release` |
| `origin/deployment/adaptive-account-viewer` | `f85bfe56e39003bcb3ff4f0d99474817569bc33c` | `remote/deployment/adaptive-account-viewer` |
| `origin/deployment/browser-fill-desktop` | `6309bd14b317013c32821140f750c4a342ef4a2d` | `remote/deployment/browser-fill-desktop` |
| `origin/deployment/novnc-cookie-context` | `0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92` | `remote/deployment/novnc-cookie-context` |
| `origin/deployment/persistent-account-devices` | `0b1c48e26c2722514d3b8786234b459cf2ac7a1f` | `remote/deployment/persistent-account-devices` |
| `origin/deployment/real-login-20261025` | `65a8669a9307b29cee925e008efcb90bf3e41986` | `remote/deployment/real-login-20261025` |
| `origin/fix/account-window-preflight` | `16fc73d6ccaaad07182e1ae4ae92b538621a1edd` | `remote/fix/account-window-preflight` |
| `origin/fix/account-window-validation` | `982b86ba1a40a0ec50126b044c5e5e35c56ea85f` | `remote/fix/account-window-validation` |
| `origin/fix/account-window-workflow` | `dbc86bd0b398fb649bf5b99e14d5daba113903d9` | `remote/fix/account-window-workflow` |
| `origin/fix/novnc-cookie-context` | `0c8fa8c35b0f768ca4c4395b4e35930f4d9cfc92` | `remote/fix/novnc-cookie-context` |
| `origin/validation/native-oauth-browser-identity` | `bf744aa5a3c7f867d9e57ab392af9933cbf3c280` | `remote/validation/native-oauth-browser-identity` |
| `origin/validation/upstream-late-interrupt` | `a843bb362e2efcf192957f6699a6960a28fcd47b` | `remote/validation/upstream-late-interrupt` |

## Validation

The audit used read-only Git metadata, patch comparison, worktree status, and GitHub API inspection. Archive tags were pushed before deletion. No local compilation, image build, executable tests, real account login, or deployment was performed. The documentation maintenance revision is submitted to the existing hosted Checks workflow, including pytest; the run URL and actual outcome are reported in the final handoff.
