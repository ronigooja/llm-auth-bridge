# Development

Use Python 3.12 and install the project with `pip install -e '.[test]'`. Run `pytest`. Keep secrets synthetic in tests and never add `auth.txt`, databases, browser profiles, or mailbox content to Git.

New adapters should define a typed credential, explicit proxy behavior, identity validation, retry semantics, and a durable task state transition. Update the architecture and integrations documents with every contract change.

