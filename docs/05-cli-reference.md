# CLI Reference

## Commands

### `generate`

Generate a Python client from an OpenAPI specification.

```bash
openapi-burrito generate <SPEC_SOURCE> [OPTIONS]
```

**Arguments:**

- `SPEC_SOURCE` - Path or URL to the OpenAPI specification (JSON or YAML)

**Options:**

- `-o, --output <DIRECTORY>` - Output directory (default: `sdk`)
- `-c, --client <async|sync>` - Client flavor(s) to generate (default:
  `async`). `async` emits `AsyncClient`, `sync` emits `Client`; repeat the
  flag (`-c async -c sync`) to emit both side by side. Class names never
  change with the modes — the flag only controls what is emitted.
- `-v, --verbose` - Enable verbose logging
- `-y, --yes` - Skip security confirmation prompt

**Examples:**

```bash
# Local file (generates AsyncClient by default)
openapi-burrito generate openapi.json -o ./my_client

# Sync client instead
openapi-burrito generate openapi.json -o ./my_client --client sync

# Remote URL
openapi-burrito generate https://petstore3.swagger.io/api/v3/openapi.json -o ./petstore

# Verbose output
openapi-burrito generate openapi.yaml -o ./client -v

# Skip confirmation (for CI/CD)
openapi-burrito generate openapi.json -o ./client -y
```

---

### `preview`

Launch a local server with Swagger UI and Redoc for previewing your OpenAPI
spec.

```bash
openapi-burrito preview <INPUT_SOURCE> [OPTIONS]
```

**Arguments:**

- `INPUT_SOURCE` - Path or URL to the OpenAPI specification

**Options:**

- `-p, --port <PORT>` - Port to run the server on (default: `8000`)

**Examples:**

```bash
# Preview local spec
openapi-burrito preview openapi.json

# Custom port
openapi-burrito preview openapi.yaml --port 3000
```

This will start a local server with:

- **Swagger UI** at `http://127.0.0.1:<port>/docs`
- **Redoc** at `http://127.0.0.1:<port>/redoc`

---

## Global Options

- `--help` - Show help message
- `--install-completion` - Install shell completion
- `--show-completion` - Show completion script
