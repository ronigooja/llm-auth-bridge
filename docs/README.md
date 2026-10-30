# Documentation map

Use this routing table before adding or updating documentation. Keep each fact in
its authority and link to it from other pages.

| Question | File |
| --- | --- |
| What capabilities are established, pending, or later scope? | [roadmap](roadmap.md) |
| What dated run, SHA, URL, or historical regression evidence supports a status? | [evidence log](evidence/2026-10-27-acceptance.md) |
| How do I deploy, upgrade, restore, or record a release? | [deployment guide](guides/deployment.md) |
| What commands build and test the project? | [development guide](guides/development.md) |
| What is the system topology or runtime boundary? | [architecture overview](architecture/overview.md) and its linked concern pages |
| What decision explains an architecture choice? | [ADR index](architecture/decisions/README.md) |
| What API or downstream behavior is contractual? | [contracts](contracts/) |
| How is a current operational failure diagnosed? | [troubleshooting](troubleshooting/) |

New incident notes go under `docs/troubleshooting/` and are linked from the
relevant guide. New dated acceptance evidence, run records, and historical
verification notes go under `docs/evidence/` (or `docs/archive/` when they are
superseded archival material) and are linked from the roadmap. New architecture
decisions go under `docs/architecture/decisions/` and are indexed in its README.
Do not put these records in architecture overview pages.
