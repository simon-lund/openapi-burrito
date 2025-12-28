> [!WARNING]
> **Early Development**: This project is under active development. APIs may
> change.

---

<div align="center">

<img src="docs/static/logo.png" alt="openapi-burrito logo" width="128" />

# openapi-burrito

**Wrap your OpenAPI specs in type-safe Python clients**

[![PyPI version](https://img.shields.io/pypi/v/openapi-burrito?style=flat&logo=pypi&logoColor=white&color=3775A9)](https://pypi.org/project/openapi-burrito/)
[![Python](https://img.shields.io/pypi/pyversions/openapi-burrito?style=flat&logo=python&logoColor=white)](https://pypi.org/project/openapi-burrito/)
[![License](https://img.shields.io/github/license/simon-lund/openapi-burrito?style=flat&color=green)](LICENSE)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.0+-6BA539?style=flat&logo=openapiinitiative&logoColor=white)](https://www.openapis.org/)

</div>

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Documentation](#documentation)
- [Examples](#examples)
- [Star History](#star-history)

## Quick Start

### Install

```bash
uv tool install openapi-burrito
```

### Generate

```bash
openapi-burrito generate openapi.json -o ./my_client
```

### Use

```python
from my_client import Client

api = Client(base_url="https://api.example.com")

# Full IDE autocomplete for paths and parameters
res = api.GET("/users/{userId}", userId=123)

if res.is_success:
    print(res.data)
else:
    print(f"Error {res.status_code}: {res.error}")
```

## Features

- **Type-Safe** - `TypedDict` models with `@overload` signatures for full IDE
  support
- **Zero Runtime** - Generated code is yours, no runtime dependency on this tool
- **httpx-Based** - Async support, connection pooling, all httpx features
- **Middleware System** - Logging, retry, auth via composable middleware

## Documentation

| Guide                                      | Description                                    |
| ------------------------------------------ | ---------------------------------------------- |
| [Getting Started](docs/getting-started.md) | Installation and basic usage                   |
| [CLI Reference](docs/cli-reference.md)     | `generate` and `preview` commands              |
| [Authentication](docs/authentication.md)   | API keys, tokens, OAuth patterns               |
| [Middleware](docs/middleware.md)           | Logging, retry, custom handling                |
| [Type System](docs/type-system.md)         | `UNSET`, `Unknown`, `NotRequired`, limitations |
| [Contributing](docs/contributing.md)       | Development setup and guidelines               |

## Examples

See the [`examples/`](examples/) directory:

- **[Petstore](examples/petstore/)** - Classic Swagger Petstore API
- **[Artifacts MMO](examples/artifactsmmo/)** - Game API with complex schemas

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=klementine/openapi-burrito&type=date&legend=top-left)](https://www.star-history.com/#klementine/openapi-burrito&type=date&legend=top-left)
