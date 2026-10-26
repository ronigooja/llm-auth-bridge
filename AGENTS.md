# Working agreement

Routine progress updates and execution details are in English. Results, important findings, risks, and decisions requested from the user are reported in Chinese. Product and project documentation is written in English.

The main agent owns architecture, contracts, coordination, integration, and final acceptance. Simple bounded tasks use `gpt-6-luna` at medium effort; code review, UI, and complex work use `gpt-6.1-sol` at medium effort. Agents modifying files use isolated worktrees under `$HOME/subagents/llm-auth-bridge/<task>`, after the main agent creates an initial commit. Each handoff includes the commit, changes, tests, and open issues.

Never read or copy real `auth.txt` in an agent task. Use synthetic fixtures. Credentials, browser state, databases, mail content, and sensitive screenshots stay out of Git; browser tracing, HAR, and video are disabled by default. Update the relevant English documentation with interface changes. Mark capabilities that have not passed real-account verification as unverified.

Run `pytest` before handoff. Do not run account logins concurrently. The main agent performs real credential verification serially.


## Git baseline and branch lifecycle

The GitHub default branch and integration target are `main`. Before development, fetch `origin`, preserve local changes, and create a new task branch from the freshly fetched `origin/main`. Do not resume a completed task branch as the next task's baseline. Record the base commit in the handoff.

Before merging, fetch again. If `origin/main` has advanced, integrate it and validate the resulting revision on GitHub-hosted Actions runners. Merge only the validated revision; never force-push or reset main to synchronize it. Run pytest on CI before handoff.

After integration, check all associated worktrees for tracked and untracked changes. Remove only clean, completed worktrees. Delete completed branches only after verifying ancestry, patch equivalence, or reviewing combined changes against main. Preserve deployment and acceptance references as tags. Preserve uncommitted work in place and report it explicitly. See `docs/branch-audit-20261026.md` for the initial cleanup and recovery references.
