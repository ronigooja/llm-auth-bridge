# Project working agreement

- When performing agent tasks, never read or copy real `auth.txt`; use synthetic fixtures. Keep credentials, browser state, databases, mail content, and sensitive screenshots out of Git. When running browser checks, disable tracing, HAR, and video by default.
- When verifying real credentials, the main agent performs account logins serially. When describing a capability without real-account acceptance, mark it as unverified.
