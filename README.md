> [!WARNING]
> **Early Development**: This project is under active development. APIs may
> change.

---

<div align="center">

<img src="https://raw.githubusercontent.com/simon-lund/openapi-burrito/main/docs/static/logo.png" alt="openapi-burrito logo" width="128" />

# openapi-burrito

**Wrap your OpenAPI specs in type-safe Python clients**

[![CI](https://github.com/simon-lund/openapi-burrito/actions/workflows/ci.yml/badge.svg)](https://github.com/simon-lund/openapi-burrito/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/openapi-burrito?style=flat&logo=pypi&logoColor=white&color=3775A9)](https://pypi.org/project/openapi-burrito/)
[![Python](https://img.shields.io/pypi/pyversions/openapi-burrito?style=flat&logo=python&logoColor=white)](https://pypi.org/project/openapi-burrito/)
[![License](https://img.shields.io/github/license/simon-lund/openapi-burrito?style=flat&color=green)](https://github.com/simon-lund/openapi-burrito/blob/main/LICENSE)
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
import asyncio

from my_client import AsyncClient


async def main():
    api = AsyncClient(base_url="https://api.example.com")

    # Path-first API: type-checked paths and snake_case parameters
    res = await api.GET("/users/{user_id}", user_id=123)

    if res.is_success:
        print(res.data)
    else:
        print(f"Error {res.status_code}: {res.error}")

    # Or let errors raise: unwrap() returns the typed body directly
    user = (await api.GET("/users/{user_id}", user_id=123)).unwrap()


asyncio.run(main())
```

Prefer sync? Generate with `--client sync` and drop the `await`s — same
paths, same overloads, `httpx.Client` underneath:

```python
from my_client import Client

api = Client(base_url="https://api.example.com")
res = api.GET("/users/{user_id}", user_id=123)
```

## Features

- **Path-First API** - Call endpoints by path literal
  (`api.GET("/users/{user_id}")`), with full IDE autocomplete for paths and
  parameters
- **Type-Safe** - `TypedDict` models and `@overload` signatures; generated
  code passes `mypy --strict`
- **Async by Default** - `AsyncClient` out of the box; `--client sync` or
  `-c async -c sync` when you need the synchronous `Client` too
- **Zero Runtime** - Generated code is yours; its only dependency is httpx
- **httpx-Based** - Connection pooling, timeouts, all httpx client features
- **Middleware System** - Logging, retry, auth via composable middleware
- **Snake Case Params** - Path parameters auto-converted to Python style
  (`{userId}` → `{user_id}`)

## Philosophy: Types Without Runtime Magic

This library has exactly one opinion: **your types should come from the spec,
and your runtime should stay out of the way.**

- **Dicts in, dicts out.** Responses are plain dicts typed as `TypedDict` —
  no model classes to instantiate, serialize, or fight with. `res.data` IS
  the parsed JSON. This is what makes the zero-runtime promise possible:
  where model classes need a deserialization layer (and that layer needs a
  runtime dependency), a `TypedDict` is erased at runtime — nothing to
  construct, no per-request overhead, nothing to import but httpx.
- **No validation, no coercion.** The generated client does not validate
  payloads against the schema and does not convert strings to `datetime`.
  Your type checker verifies structure at development time; at runtime you
  get what the API sent, untouched.
- **No inheritance hooks, no plugins, no config file.** One command in, one
  small readable package out.

If you want runtime validation and rich models, you want a
[pydantic](https://docs.pydantic.dev)-based generator like
[openapi-python-client](https://github.com/openapi-generators/openapi-python-client)
— that's a great tool with a different philosophy. openapi-burrito is for
when you'd rather have the thinnest possible typed layer over httpx.

If you build **FastAPI** services, this will feel like home: the same
httpx + type-hints + async idioms you already use, pointed at the APIs you
*consume* instead of the ones you serve.

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

Code generators turn untrusted input into code, so the design has to make
injection impossible rather than filter it out. **Always review untrusted
specs before generating** anyway.

### How spec text reaches generated code

Nothing from the spec is concatenated into source as-is. Every value takes
one of these paths:

| What                                  | How it is emitted                 | Guarantee                                              |
| ------------------------------------- | --------------------------------- | ------------------------------------------------------ |
| Model and argument names              | `spec.naming.identifier()`        | Valid, non-keyword identifier or generation fails      |
| Model property keys                   | Verbatim in class syntax if a plain identifier, else `repr()` in functional `TypedDict` syntax | Keys match the wire format; never hand-escaped |
| Paths, enum values, defaults, wire names | `repr()`                       | A Python literal that evaluates back to the exact value |
| Descriptions/docs                     | `emit.python.docstring()`         | Backslashes, triple quotes and control chars escaped; property-tested for every string |
| Types                                 | Rendered from the IR by `match`   | Only known constructors; unknown schemas become `Any`  |
| `method`, parameter `in`              | `ir.Method` / `ir.Location` enums | Unknown values are skipped with a warning              |
| `required`, `readOnly`, `writeOnly`   | `bool()` cast                     | Forced to boolean                                      |
| The runtime (`Response`, `UNSET`, …)  | Copied verbatim from `runtime.py` | Never templated; type-checked and tested in this repo  |
| pyproject.toml metadata               | JSON-escape                       | TOML-safe string literals                              |

As defense in depth, every emitted `.py` file must pass `compile()` and the
`pyproject.toml` must parse as TOML before anything is written to disk —
malformed output aborts generation instead of landing in your project.

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
| [Introduction](https://github.com/simon-lund/openapi-burrito/blob/main/docs/01-introduction.md)     | Installation and basic usage                   |
| [Authentication](https://github.com/simon-lund/openapi-burrito/blob/main/docs/02-authentication.md) | API keys, tokens, OAuth patterns               |
| [Middleware](https://github.com/simon-lund/openapi-burrito/blob/main/docs/03-middleware.md)         | Logging, retry, custom handling                |
| [Type System](https://github.com/simon-lund/openapi-burrito/blob/main/docs/04-type-system.md)       | `UNSET`, `Unknown`, `NotRequired`, limitations |
| [CLI Reference](https://github.com/simon-lund/openapi-burrito/blob/main/docs/05-cli-reference.md)   | `generate` and `preview` commands              |
| [Contributing](https://github.com/simon-lund/openapi-burrito/blob/main/docs/06-contributing.md)     | Development setup and guidelines               |
| [Architecture](https://github.com/simon-lund/openapi-burrito/blob/main/docs/07-architecture.md)     | `load` → `parse` → `emit`, the IR, tree vs graph |

## Examples

See the [`examples/`](https://github.com/simon-lund/openapi-burrito/tree/main/examples/) directory:

- **[Petstore](examples/petstore/)** - Classic Swagger Petstore API
- **[Artifacts MMO](examples/artifactsmmo/)** - Game API with complex schemas

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=klementine/openapi-burrito&type=date&legend=top-left)](https://www.star-history.com/#klementine/openapi-burrito&type=date&legend=top-left)
