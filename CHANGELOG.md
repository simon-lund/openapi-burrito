# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow
[SemVer](https://semver.org/) (0.x: minor bumps may break).

## [0.2.0] - 2026-07-17

### Breaking

- **Async by default**: `generate` now emits `AsyncClient` unless told
  otherwise. Use `--client sync` for the synchronous `Client` or
  repeat the flag (`-c async -c sync`) for both. Class names never
  change with the modes.
- **Keyword-only parameters**: all arguments after `path` must be passed by
  keyword (`api.GET("/pet/{pet_id}", pet_id=1)`); this matches the runtime
  routing and makes the `@overload` surface sound under `mypy --strict`.
- Model property names are no longer renamed: TypedDict keys match the wire
  format exactly (`type` stays `type`, `user-name` stays `"user-name"` via
  functional syntax) — code that used sanitized names like `type_` must
  switch to the real keys.
- Response unions containing `Any` collapse to `Any`.
- The generated `Response` is a thin delegating wrapper; `status_code` etc.
  remain available as typed properties.

### Added

- `AsyncClient` with async middleware support (`AsyncMiddlewareT`).
- Repeatable `--client async|sync` CLI flag (default: `async`).
- `Response.unwrap()` returning the typed body directly, raising
  `ResponseError` (with the full typed response attached) on non-2xx.
- Recursive schemas (`$ref` cycles) now generate correctly.
- `anyOf` translates to a union instead of `Any`; OpenAPI 3.1 type arrays
  and `oneOf` with `null` keep `| None`; `nullable` on `$ref` siblings works.
- `+json` MIME suffixes recognized for request bodies and responses.
- Raw request bodies via the `content` argument (`application/octet-stream`).
- Escape hatch: paths not in the spec send kwargs as path/query params
  (typed via a catch-all overload).
- Generation gates: every emitted `.py` must pass `compile()` and the
  `pyproject.toml` must parse before anything is written.
- Generated code is post-formatted with ruff and passes `mypy --strict`
  (verified against the GitHub, Stripe, and converted Slack specs).
- Clear error for Swagger 2.0 documents, pointing at `swagger2openapi`.

### Fixed

- Every generated request crashed with a `Response` constructor `TypeError`
  (template drift between `client.py` and `models.py`).
- Request bodies were silently dropped for `content` uploads and for
  methods without body slots (e.g. JSON bodies on DELETE).
- Parameters defined at path level and overridden at operation level, or
  colliding after snake_casing, produced duplicate arguments
  (`SyntaxError` on import). Colliding parameters are now renamed
  deterministically; the body slots never are.
- A query parameter named `json` no longer shadows the JSON body slot.
- `X-Trace-Id`-style names no longer snake_case to `x__trace__id`.
- Unknown kwargs on spec-defined paths raise `TypeError` instead of being
  silently discarded.
- Malformed JSON responses fall back to raw bytes instead of raising.
- `.yml` spec files accepted by `preview`.
- The generated `pyproject.toml` uses the spec's real version and no longer
  depends on the unused `cattrs`.

### Security

- Docstring sanitization escapes backslashes (a trailing `\` could swallow
  the closing quotes).
- All strings interpolated into the generated `pyproject.toml` are
  TOML-escaped.
- The `compile()` gate turns any escaping gap into a loud generation-time
  failure instead of emitted code.

## [0.1.1] - 2026-01-05

- README link fixes for PyPI.

## [0.1.0] - 2026-01-05

- Initial release: path-first typed client generation (`@overload` per
  operation, TypedDict models), middleware system, `preview` command.
