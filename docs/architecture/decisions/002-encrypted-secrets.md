# ADR 002: Encrypted secrets

## Context

The bridge must retain credentials and browser state across task and process
lifetimes. SQLite persistence and backups should not contain reusable plaintext
account secrets. Browser recovery and delayed downstream synchronization extend
the set of sensitive records beyond initial account passwords.

## Decision

When storing reusable account, browser or integration secret material, encrypt it
with AES-GCM under a separately mounted key. Keep administrator passwords and
session tokens hashed, and expose only sanitized public fields.

When storing a native device archive, authenticate its account ID as additional
associated data to reject cross-account ciphertext substitution. Keep runtime
plaintext device directories temporary and restricted. The implementation is in
[crypto.py](../../../app/crypto.py) and device controls in
[worker.py](../../../app/worker.py).

## Consequences

A database backup requires its matching key; a compromised runtime or host can
still access material in use. New durable secret types must use the same storage
boundary, while runtime handling is defined in [runtime](../runtime.md) and
backup procedures in [deployment](../../guides/deployment.md).
