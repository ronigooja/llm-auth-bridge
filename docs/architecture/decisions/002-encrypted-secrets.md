# ADR 002: Encrypted secrets

## Context

The bridge must retain credentials and browser state across task and process
lifetimes. SQLite persistence and backups should not contain reusable plaintext
account secrets. Browser recovery and delayed downstream synchronization extend
the set of sensitive records beyond initial account passwords.

## Decision

When storing reusable account, browser or integration secret material, encrypt it
with AES-GCM under a 32-byte key supplied as a separately mounted secret file.
Keep administrator passwords as Argon2id hashes and session tokens as SHA-256
hashes. Ordinary public responses return sanitized fields and presence flags.

When storing a native device archive, authenticate its account ID as additional
associated data to reject cross-account ciphertext substitution. Keep runtime
plaintext device directories temporary and restricted. The implementation is in
[crypto.py](../../../app/crypto.py) and device controls in
[worker.py](../../../app/worker.py).

## Consequences

A database backup requires its matching key to recover encrypted data. The key
must be restored separately and startup must validate the encrypted key check.
A compromised runtime or host can still access material being used; at-rest
encryption does not protect against that threat. New durable secret types must
use the same storage boundary, and safe public serialization remains a separate
responsibility. See [security](../security.md) for the current protected data and
[deployment](../../guides/deployment.md) for backup and restore procedures.
