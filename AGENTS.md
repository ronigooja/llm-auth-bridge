# Project working agreement

- When communicating during repository work, use English for routine progress and execution details, and Chinese for results, important findings, risks, and decisions requested from the user. Write product and project documentation in English.
- When implementing a project change, the main agent owns architecture, contracts, coordination, integration, and final acceptance. For interface changes, update the relevant English documentation.
- When performing agent tasks, never read or copy real `auth.txt`; use synthetic fixtures. Keep credentials, browser state, databases, mail content, and sensitive screenshots out of Git. When running browser checks, disable tracing, HAR, and video by default.
- When verifying real credentials, the main agent performs account logins serially. When describing a capability without real-account acceptance, mark it as unverified.
- When handing off changes, include the base and result commits, changed files, pytest/CI results, and open issues. Run pytest on CI before handoff.
- Before integration into `main`, fetch `origin` again, incorporate any newer main commits, and validate the resulting revision on GitHub-hosted Actions runners. Merge only the validated revision; never force-push or reset main to synchronize it.
- After integration, inspect associated worktrees for tracked and untracked changes. Remove only clean, completed worktrees; delete completed branches only after verifying integration. Keep deployment and acceptance references as tags, and preserve and report uncommitted work in place.
