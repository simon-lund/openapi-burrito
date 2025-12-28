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
├── generator.py        # Main generation logic
├── utils.py            # Shared utilities (snake_case, normalize_path)
├── parser/
│   ├── lookup.py       # Schema lookup via content hashing
│   ├── models.py       # Parsed data models (ParsedOperation, etc.)
│   ├── operation.py    # Parser for paths/operations
│   ├── sanitize.py     # Security-critical sanitization
│   ├── schema.py       # Parser for component schemas
│   └── types.py        # Type translation (OpenAPI → Python)
└── templates/          # Jinja2 templates
    ├── client.py.jinja2
    ├── models.py.jinja2
    └── ...
```

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
