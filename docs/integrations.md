# Integrations

CLIProxyAPI receives a typed `codex_oauth` credential after a PKCE exchange performed through the account route. The bridge validates OAuth state, uploads the compatible credential, verifies remote identity and proxy, then removes its refresh-token copy after successful synchronization. Failed uploads remain retryable.

chatgpt-web-voice receives a `chatgpt_web` access token through its administrator API. Existing remote IDs are updated rather than duplicated. Expiry checks are scheduled; an invalid browser session becomes `reauth_required` and does not repeatedly submit a password.

These integrations are contracts only in this repository and require real endpoint verification before being advertised as supported.

