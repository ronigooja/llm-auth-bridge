# OAuth through the account route

OAuth authorization and code exchange use the same explicit account route. This prevents a successful browser login from producing a token through a different network identity and avoids silently falling back to direct access when a proxy fails.

