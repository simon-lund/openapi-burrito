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
- [Installation](#installation)
- [Documentation](#documentation)
- [Examples](#examples)
- [Star History](#star-history)

## Quick Start

```bash
# Install
uv tool install openapi-burrito

# Generate
openapi-burrito generate openapi.json -o ./my_client
```

```python
from my_client import Client

api = Client(base_url="https://api.example.com")

# Path-first API: type-checked paths and snake_case parameters
res = api.GET("/users/{user_id}", user_id=123)

if res.is_success:
    print(res.data)
else:
    print(f"Error {res.status_code}: {res.error}")
```

## Features

- **Path-First API** - Call endpoints by path literal
  (`api.GET("/users/{user_id}")`), with full IDE autocomplete for paths and
  parameters
- **Type-Safe** - `TypedDict` models and `@overload` signatures
- **Zero Runtime** - Generated code is yours, no runtime dependency on this tool
- **httpx-Based** - Async support, connection pooling, all httpx features
- **Middleware System** - Logging, retry, auth via composable middleware
- **Snake Case Params** - Path parameters auto-converted to Python style
  (`{userId}` → `{user_id}`)

## Installation

### For Users

```bash
# As a CLI tool (recommended)
uv tool install openapi-burrito

# With preview server support (Swagger UI, Redoc)
uv tool install openapi-burrito[preview]
```

### For Developers

```bash
# Clone and install all dev dependencies
git clone https://github.com/simon-lund/openapi-burrito.git
cd openapi-burrito
make install

# Run linting and type checks
make lint

# Run tests
make test
```

## Security

This generator sanitizes identifiers and string literals to prevent code
injection from malformed OpenAPI specs. However, **always review untrusted specs
before generating**.

### Parser Safety Audit

All fields output by the parser are validated/sanitized:

| Field                                 | Validation             | Notes                                 |
| ------------------------------------- | ---------------------- | ------------------------------------- |
| Model/param names                     | `sanitize(mode="id")`  | Converted to valid Python identifiers |
| Paths                                 | `sanitize(mode="str")` | String-escaped for literals           |
| Descriptions/docs                     | `sanitize(mode="doc")` | Docstring-escaped                     |
| `type` strings                        | Type translator        | Built from validated schema types     |
| `method`                              | `HTTPMethod` enum      | Only known HTTP methods allowed       |
| `in` (param location)                 | Enum check             | Only `path\|query\|header\|cookie`    |
| `required`, `read_only`, `write_only` | `bool()` cast          | Forced to boolean                     |
| `default`                             | `repr()`               | Python string representation          |

A malicious spec could attempt injection like:

```yaml
components:
  schemas:
    "User:\n    pass\nimport os; os.system('rm -rf /')  # ":
      type: object
```

While this generator escapes such payloads, the safest approach is to only
generate clients from trusted sources.

See
[CVE-2020-15142](https://github.com/openapi-generators/openapi-python-client/security/advisories/GHSA-9x4c-63pf-525f)
for an example of this vulnerability class in other generators.

## Documentation

| Guide                                       | Description                                    |
| ------------------------------------------- | ---------------------------------------------- |
| [Introduction](docs/01-introduction.md)     | Installation and basic usage                   |
| [Authentication](docs/02-authentication.md) | API keys, tokens, OAuth patterns               |
| [Middleware](docs/03-middleware.md)         | Logging, retry, custom handling                |
| [Type System](docs/04-type-system.md)       | `UNSET`, `Unknown`, `NotRequired`, limitations |
| [CLI Reference](docs/05-cli-reference.md)   | `generate` and `preview` commands              |
| [Contributing](docs/06-contributing.md)     | Development setup and guidelines               |

## Examples

See the [`examples/`](examples/) directory:

- **[Petstore](examples/petstore/)** - Classic Swagger Petstore API
- **[Artifacts MMO](examples/artifactsmmo/)** - Game API with complex schemas

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=klementine/openapi-burrito&type=date&legend=top-left)](https://www.star-history.com/#klementine/openapi-burrito&type=date&legend=top-left)
