# Project working agreement

- When performing agent tasks, never read or copy real `auth.txt`; use synthetic fixtures. Keep credentials, browser state, databases, mail content, and sensitive screenshots out of Git. When running browser checks, disable tracing, HAR, and video by default.
- When verifying real credentials, the main agent performs account logins serially. When describing a capability without real-account acceptance, mark it as unverified.
- Use [docs/README.md](docs/README.md) to route documentation changes and find each fact's authority.
- Use [docs/guides/development.md](docs/guides/development.md) for build and test commands.
- When writing documentation, keep repository documentation in English, state when each rule applies, define each fact once in its authoritative file, and link to it elsewhere.
