# Artifacts MMO Example

Generated client for the [Artifacts MMO API](https://artifactsmmo.com/).

## Generate the Client

```bash
uv run openapi-burrito generate examples/artifactsmmo/openapi.json -o examples/artifactsmmo/client -y
```

## Run the Demo

```bash
# Public endpoints (no auth required)
uv run python examples/artifactsmmo/main.py

# With authentication (get token from https://artifactsmmo.com/account)
export ARTIFACTS_TOKEN="your_token_here"
uv run python examples/artifactsmmo/main.py
```

The demo:

1. Checks server status (public)
2. Lists items (public)
3. Lists your characters (requires token)

## Authentication

The demo uses middleware to inject the Bearer token. See
[docs/authentication.md](../../docs/authentication.md) for other patterns.
