# Encrypted secrets

Passwords, TOTP seeds, mailbox URLs, downstream configuration, and future browser storage state are encrypted with AES-GCM. The 32-byte key is supplied as a separately mounted secret file. Plaintext values are never returned by ordinary API responses.

