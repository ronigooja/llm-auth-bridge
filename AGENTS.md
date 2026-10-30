# Project working agreement

- When implementing a project change, the main agent owns architecture, contracts, coordination, integration, and final acceptance. For interface changes, update the relevant English documentation.
- When performing agent tasks, never read or copy real `auth.txt`; use synthetic fixtures. Keep credentials, browser state, databases, mail content, and sensitive screenshots out of Git. When running browser checks, disable tracing, HAR, and video by default.
- When verifying real credentials, the main agent performs account logins serially. When describing a capability without real-account acceptance, mark it as unverified.
- After integration, inspect associated worktrees for tracked and untracked changes. Remove only clean, completed worktrees; delete completed branches only after verifying integration. Keep deployment and acceptance references as tags, and preserve and report uncommitted work in place.
