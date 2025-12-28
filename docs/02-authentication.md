# Authentication

Since the generated client wraps [httpx](https://www.python-httpx.org/), all
authentication methods work exactly as documented in
[httpx's auth guide](https://www.python-httpx.org/advanced/authentication/).

## Headers (API Keys, Tokens)

Pass authentication headers directly to the client:

```python
from my_client import Client

# API Key
client = Client(
    base_url="https://api.example.com",
    headers={"X-API-Key": "your-api-key"}
)

# Bearer Token
client = Client(
    base_url="https://api.example.com",
    headers={"Authorization": "Bearer your-token"}
)
```

## httpx.Auth (Advanced)

For more complex auth flows (token refresh, signing), use `httpx.Auth`:

```python
import httpx

class BearerAuth(httpx.Auth):
    def __init__(self, token: str):
        self.token = token

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request

client = Client(
    base_url="https://api.example.com",
    auth=BearerAuth("your-token")
)
```

## Middleware-based Auth

Inject authentication via middleware for dynamic tokens:

```python
@client.middleware
def auth_middleware(request, call_next):
    token = get_current_token()  # Your token logic
    request.headers["Authorization"] = f"Bearer {token}"
    return call_next(request)
```

## Cookies

```python
client = Client(
    base_url="https://api.example.com",
    cookies={"session_id": "abc123"}
)
```
