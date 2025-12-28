# Type System

This document explains the type patterns used in generated clients.

## TypedDict Models

All OpenAPI schemas are generated as Python `TypedDict` classes:

```python
class User(TypedDict):
    id: int
    name: str
    email: NotRequired[str]
```

### Required vs Optional Fields

| OpenAPI             | Python Type                      |
|---------------------| -------------------------------- |
| Required            | `name: str`                      |
| Optional            | `name: NotRequired[str]`         |
| Required + Nullable | `name: str \| None`              |
| Optional + Nullable | `name: NotRequired[str \| None]` |

> **Note:** `NotRequired` is from `typing` and indicates the key can be omitted.
> `| None` indicates the value can be `null`.

---

## Special Types

### `UNSET` Sentinel

For optional parameters, the generator uses an `UNSET` sentinel to distinguish
between:

- **Omitted** (not sent in request)
- **Explicit null** (sent as `null`)

```python
from my_client import UNSET

# Omit the parameter entirely
api.PATCH("/users/{user_id}", user_id=1, nickname=UNSET)

# Send null explicitly
api.PATCH("/users/{user_id}", user_id=1, nickname=None)
```

### `REQUIRED` Sentinel

For required parameters that need to appear after optional parameters (to
maintain a consistent grouping: path → body → query -> ...), the generator uses a
`REQUIRED` sentinel:

```python
from my_client import REQUIRED

# Required parameters use REQUIRED as a sentinel default
# This allows them to be placed after optional parameters
# while still requiring the caller to provide a value
api.POST("/items", name=REQUIRED, category="books")
```

If you call a method without providing a required parameter, you'll get a
`TypeError` at runtime.

---

## Limitations

### `oneOf` / `anyOf`

Polymorphic types (`oneOf`, `anyOf`) are mapped to Python `Union` types:

```python
# OpenAPI: oneOf: [Cat, Dog]
# Generated: Cat | Dog
```

> **Note:** Discriminator handling is not yet implemented. The generated union
> includes all possible types, but runtime validation is left to the caller.

### `additionalProperties`

Objects with only `additionalProperties` become `dict[str, T]`:

```python
# OpenAPI: type: object, additionalProperties: {type: string}
# Generated: dict[str, str]
```

### Binary Data

Binary fields (`type: string, format: binary`) become `bytes`:

```python
# OpenAPI: type: string, format: binary
# Generated: bytes
```

---

## Response Type

All methods return a `Response[T, E]` wrapper around `httpx.Response`:

```python
@dataclass
class Response(Generic[T, E]):
    status_code: int
    _response: httpx.Response

    # Typed accessors
    data: T | None   # Success body
    error: E | None  # Error body

    # Status helpers
    is_informational: bool # 1xx
    is_success: bool       # 2xx
    is_redirect: bool      # 3xx
    is_client_error: bool  # 4xx
    is_server_error: bool  # 5xx
    is_error: bool         # 4xx or 5xx
```

### Response Handling Pattern

| Status Category     | Typed Body         | Accessor | Notes                          |
| :------------------ | :----------------- | :------- | :----------------------------- |
| **2xx** (Success)   | `T` (e.g. `User`)  | `.data`  | `.error` is `None`             |
| **4xx/5xx** (Error) | `E` (e.g. `Error`) | `.error` | `.data` is `None`              |
| **1xx** (Info)      | `Any`              | N/A      | Use `.status_code`, `.headers` |
| **3xx** (Redirect)  | `Any`              | N/A      | Use `.headers["Location"]`     |

### Usage Example

```python
res = api.GET("/users/{user_id}", user_id=123)

if res.is_success:
    user = res.data  # Typed as User
    print(user["name"])
elif res.is_redirect:
    print(f"Redirecting to: {res.headers['Location']}")
elif res.is_error:
    print(f"Error {res.status_code}: {res.error}")
```
