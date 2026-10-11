# Contributing

Thank you for considering contributing to `openapi-burrito`! 🌯

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/simon-lund/openapi-burrito.git
   cd openapi-burrito
   ```

2. **Install all dependencies and hooks:**
   ```bash
   make install
   ```

3. **Run linting and type checks:**
   ```bash
   make lint
   ```

4. **Run tests:**
   ```bash
   make test
   # or directly:
   uv run pytest
   ```

5. **Generate a test client:**
   ```bash
   uv run openapi-burrito generate examples/petstore/openapi.json -o /tmp/test-client -y
   ```

## Project Structure

```
openapi_burrito/
├── cli.py              # CLI entry point (Typer)
├── generator.py        # generate(): load → parse → emit → write → format
├── ir.py               # The intermediate representation (Api, Model, Operation, type expressions)
├── runtime.py          # Response, UNSET/REQUIRED, middleware, prepare_request — vendored into every client
├── spec/               # Frontend: OpenAPI document → ir.Api
│   ├── load.py         # prance loading, Swagger 2 detection
│   ├── resolver.py     # Internal $ref resolution
│   ├── naming.py       # Identifiers, snake_case, collision renaming
│   ├── types.py        # JSON Schema → type expression
│   ├── schemas.py      # components/schemas → Model
│   └── operations.py   # paths → Operation
└── emit/               # Backend: ir.Api → source files
    ├── python.py       # All Python spelling: types, literals, docstrings, views
    └── templates/      # Jinja2 layout only
```

Read [Architecture](07-architecture.md) before changing anything structural:
it explains why the IR is a tree of values with symbolic references, and
which concern lives where.

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run `make lint` and `make test`
5. Commit with a clear message
6. Push and open a PR

## Reporting Issues

Please include:

- OpenAPI spec (or minimal reproduction)
- Expected vs actual behavior
- Python version and OS
