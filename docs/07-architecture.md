# Architecture

openapi-burrito is a small compiler. Like every compiler it has three parts,
and the whole design follows from keeping them apart:

```
OpenAPI document  ──parse──▶  Api (the IR)  ──emit──▶  Python source
   spec/                        ir.py                   emit/
```

- **`spec/`** reads an OpenAPI document and builds the IR. It knows OpenAPI
  (refs, `allOf`, `nullable`, content types) and nothing about Python.
- **`ir.py`** is the vocabulary: a few frozen dataclasses that describe an
  API — its models, operations, parameters and the types of their values.
  It knows neither OpenAPI nor Python. It is the only thing the two sides
  share, and it is the part you can print, inspect and transform.
- **`emit/`** turns an `Api` into source files. It is the only place that
  knows how Python spells things: `NotRequired[...]`, `Query[...]`,
  `str | None`, `Literal["a"]`, `REQUIRED`, docstring escaping.
- **`runtime.py`** is a real module — `Response`, `UNSET`/`REQUIRED`, the
  middleware chain, `prepare_request` — that is type-checked and tested here
  and copied *verbatim* into every generated package as `_runtime.py`. The
  generated client has zero dependency on the generator because the runtime
  is vendored, not because it is templated.

The public Python API is four verbs:

```python
from openapi_burrito import load, parse, emit, generate

doc = load("openapi.yaml")            # dict, external $refs resolved
api = parse(doc)                      # ir.Api
files = emit(api, modes=("async",))   # {"client.py": "...", "models.py": "...", ...}
generate("openapi.yaml", "sdk/")      # load → parse → emit → validate → write → format
```

Each step is a pure function of the previous one. You can stop anywhere,
look at what you have, change it, and continue:

```python
api = parse(load("github.yaml"))
api = replace(api, operations=[op for op in api.operations if "repos" in op.tags])
emit(api)
```

## The IR

`ir.py` is deliberately tiny. If it grows past ~200 lines, a feature has
leaked in that belongs in `spec/` or `emit/`.

```python
# What a JSON value may be
Primitive(kind)       kind: "string" | "integer" | "number" | "boolean" | "binary" | "null"
Any, Never            the `true` / `false` schemas
Ref(name)             a named model, by name — see "Tree or graph" below
Array(item)
Map(value)            object with additionalProperties → dict[str, value]
Union(members)        oneOf / anyOf / nullable / OpenAPI 3.1 type lists
Enum(values)          JSON-schema enum; values are str | int | bool | None only

# The API
Field(name, type, required, doc, default, read_only, write_only)
Model(name, fields, doc)
Param(name, api_name, location, type, required, default, doc)
Body(slot, type, required, doc)
Operation(method, path, params, body, responses, doc, tags, operation_id)
Api(title, version, description, models, operations)
```

Three rules keep it algebraic:

1. **Nullability is a `Union` containing `Primitive("null")`**, not a flag on
   every node. `union(*members)` is a normalizing factory: it flattens nested
   unions, dedupes, collapses a single member, and lets `Any` absorb the rest.
   The dataclasses are dumb; the factory is smart.
2. **Defaults are `Default(value) | None`**, so `Default(None)` ("defaults to
   JSON null") is distinct from `None` ("no default"). `Param` carries
   `required` and `default`; the emitter decides whether that renders as
   `REQUIRED`, `UNSET`, or a literal.
3. **Responses are kept per status** (`{200: Ref("Pet"), 404: Ref("Error")}`).
   `Operation.success` and `Operation.error` are derived unions, not stored
   strings. Keeping the information and deriving views is the whole point of
   having an IR.

Node names follow JSON Schema rather than `typing` (`Array` not `List`,
`Enum` not `Literal`, `Map` not `Dict`). Partly because it describes what is
on the wire, partly because the `typing` names collide with the imports every
module needs.

## Tree or graph?

Three different structures hide in "the thing we build", and they want
different treatment.

**Containment is a tree.** `Api` holds operations, an operation holds
params, a param holds a type, a type holds sub-types. Every node has exactly
one parent. This is what gets printed, walked, pattern-matched, and compared
for equality — so it is built from frozen dataclasses with value semantics.
Two `Ref("Pet")` are equal; nothing is ever compared by identity.

**Reference is a graph.** `Ref("Pet")` points at `api.models["Pet"]`, whose
fields may point back (`Tree.children: Array(Ref("Tree"))`, or `User ↔ Pet`).
That graph is directed and cyclic in general. It is *not* stored as object
pointers: pointer-linked cycles break `__eq__`, `__hash__`, `__repr__` and
pickling, and have a construction-order problem (to build `User` you need
`Pet`, which needs `User`). A `Ref` is a name; `Api.models` is the symbol
table; the graph is whatever you compute when you ask:

```python
api.models["Pet"].refs()        # frozenset of model names this model reaches directly
api.dependencies()              # {model: {models it references}}
```

This is the same decision every compiler makes (AST + symbol table), the
same one PyTorch makes (`nn.Module` is a tree of children; `named_modules()`
and the FX graph are derived views; parameter sharing is "the same Parameter
referenced twice", discovered when you ask, not stored as an edge), and the
same one JSON Schema makes (`$ref` is a name; the document is a tree).

**Identity is a non-issue.** In the spec, one schema dict may be reachable
from many places. In the IR it becomes equal values in many places. Nothing
downstream needs to know they were once the same object.

When is the graph actually needed? Reachability (prune unused models, split
a client by tag) is a one-liner over `dependencies()`. Ordering is used today:
`api.dependency_order()` emits models dependencies-first, so functional-syntax
TypedDicts — which are *calls*, evaluated at import — can use real
annotations instead of quoted forward references; only a reference that
closes a genuine cycle (`Tree → Tree`) is still spelled as a string.
Class-syntax models never cared, thanks to `from __future__ import
annotations`. So: tree of values, symbolic refs, graph on demand.

## Where each concern lives

| Concern | Lives in | Not in |
|---|---|---|
| `$ref` resolution, `allOf` flattening, content-type negotiation | `spec/` | — |
| Identifier sanitizing, snake_case, collision renaming | `spec/naming.py` | templates |
| Python spelling of types, defaults, docstrings | `emit/python.py` | `spec/` |
| Signature order (`path, body, query, header, cookie`), keyword-only `*` | `emit/` | `spec/` |
| TypedDict class vs functional syntax | `emit/` (a property of the model's keys) | `ir` |
| `Response`, sentinels, middleware, request building | `runtime.py` | templates |
| Spec-dependent layout only: overload stubs, TypedDict bodies, `_PARAM_MAP` | `emit/templates/` | — |

The `compile()` gate on every emitted file stays as defense in depth, but it
is no longer load-bearing: string literals are rendered with `repr()`,
identifiers are validated with `str.isidentifier()`, and the runtime is never
templated — there is no string concatenation left for a hostile spec to
break out of.
