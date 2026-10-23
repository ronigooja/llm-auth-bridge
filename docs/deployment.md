# Deployment

Create `.secrets/master_key` as a random 32-byte file with mode `0600`, then run Docker Compose. The published port is loopback-only. Use SSH forwarding or an HTTPS reverse proxy for remote administration. Back up the SQLite volume and the master key together; either alone is insufficient for recovery. Rotate keys with a planned decrypt-and-reencrypt migration.

