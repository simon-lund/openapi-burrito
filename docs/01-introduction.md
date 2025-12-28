# Introduction

This guide covers installation and basic usage of `openapi-burrito`.

## Installation

We recommend using [uv](https://docs.astral.sh/uv/) for fast, isolated
installation:

```bash
uv tool install openapi-burrito
```

## Generate a Client

Point the CLI to your OpenAPI spec (local file or URL) and specify an output
directory:

```bash
openapi-burrito generate openapi.json -o ./my_client
```

This creates a self-contained Python package with:

| File             | Description                                                     |
| ---------------- | --------------------------------------------------------------- |
| `client.py`      | Main client with typed `@overload` signatures for each endpoint |
| `models.py`      | All API schemas as `TypedDict` definitions                      |
| `pyproject.toml` | Dependencies (`httpx`)                                          |
| `__init__.py`    | Package exports                                                 |

## Basic Usage

```python
from my_client import Client

# Initialize with base URL
api = Client(base_url="https://api.example.com")

# GET request with path parameter (note: snake_case)
res = api.GET("/users/{user_id}", user_id=123)

if res.is_success:
    print(res.data)
else:
    print(f"Error: {res.error}")

# POST request with JSON body
res = api.POST("/users", json={"name": "Alice", "email": "alice@example.com"})
```

> **Note**: Path parameters are automatically converted to snake_case. OpenAPI's
> `{userId}` becomes `{user_id}` in the generated client.

## httpx Configuration

The generated client wraps [httpx](https://www.python-httpx.org/), so all
`httpx.Client` constructor arguments are supported:

```python
client = Client(
    base_url="https://api.example.com",
    timeout=30.0,
    headers={"User-Agent": "MyApp/1.0"},
    proxies={"https://": "http://localhost:8080"},
    verify=False,  # Disable SSL verification (dev only)
)
```

See [httpx documentation](https://www.python-httpx.org/) for all available
options.

## Next Steps

- [CLI Reference](cli-reference.md) - All commands and options
- [Authentication](authentication.md) - API keys, tokens, OAuth
- [Middleware](middleware.md) - Logging, retry, custom handling
- [Type System](type-system.md) - Understanding generated types
