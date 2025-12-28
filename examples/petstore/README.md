# Petstore Example

Generated client for the [Petstore V3 API](https://petstore3.swagger.io/).

## Generate the Client

```bash
uv run openapi-burrito generate examples/petstore/openapi.json -o examples/petstore/client -y
```

## Run the Demo

```bash
uv run python examples/petstore/main.py
```

The demo shows:

1. GET request to find pets by status
2. POST request to create a new pet
3. GET request to retrieve a pet by ID
4. DELETE request to remove a pet

Uses middleware for request logging and retry logic. See
[docs/middleware.md](../../docs/middleware.md) for more patterns.
