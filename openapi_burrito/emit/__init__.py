"""
The Python backend: ``ir.Api`` → source files.

This is the only module that knows how Python spells things — ``str | None``,
``NotRequired[...]``, ``Query[...]``, ``Literal["a"]``, ``REQUIRED``, how a
docstring is escaped. The templates receive pre-rendered strings and do
layout only.

Nothing here concatenates untrusted text into code: every literal goes
through ``repr()``, every identifier was validated by ``spec.naming``, and the
runtime is copied, not templated. The ``compile()`` gate on every emitted file
is defense in depth.
"""

import keyword
import math
import re
import tomllib
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from jinja2 import Environment, FileSystemLoader

from .. import ir, runtime

Mode = Literal["async", "sync"]
"""Client flavors. The one definition: emit validates against it, the CLI
offers it as choices."""
MODES: tuple[Mode, ...] = get_args(Mode)
DEFAULT_MODES: tuple[Mode, ...] = ("async",)

TEMPLATES = Path(__file__).parent / "templates"


class GenerationError(Exception):
    """Raised when the emitted output would be invalid; nothing is written."""


# ---------------------------------------------------------------------------
# Spelling
# ---------------------------------------------------------------------------

PRIMITIVES: dict[ir.PrimitiveKind, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "binary": "bytes",
    "null": "None",
}

WRAPPERS: dict[ir.Location, str] = {
    ir.Location.QUERY: "Query",
    ir.Location.HEADER: "Header",
    ir.Location.COOKIE: "Cookie",
}
"""Documentary annotations: a reader can tell a header from a query parameter
in the signature. Routing is done by _PARAM_MAP."""


def render_type(expr: ir.TypeExpr) -> str:
    match expr:
        case ir.Primitive(kind):
            return PRIMITIVES[kind]
        case ir.Any():
            return "Any"
        case ir.Never():
            return "Never"
        case ir.Ref(name):
            return name
        case ir.Array(item):
            return f"list[{render_type(item)}]"
        case ir.Map(value):
            return f"dict[str, {render_type(value)}]"
        case ir.Union(members):
            parts = sorted(render_type(m) for m in members if m != ir.NULL)
            if ir.NULL in members:
                parts.append("None")  # None always last
            return " | ".join(parts)
        case ir.Enum(values):
            return f"Literal[{', '.join(literal(v) for v in values)}]"


def literal(value: Any) -> str:
    """
    A Python literal for a JSON value. ``repr`` is exact for every JSON type;
    anything else (a YAML date, say) is stringified so the output stays valid.
    """
    match value:
        case float() if not math.isfinite(value):
            return f"float({str(value)!r})"  # inf / -inf / nan have no literal
        case None | bool() | int() | float() | str():
            return repr(value)
        case list():
            return f"[{', '.join(literal(v) for v in value)}]"
        case dict():
            items = ", ".join(f"{literal(k)}: {literal(v)}" for k, v in value.items())
            return f"{{{items}}}"
        case _:
            return repr(str(value))


def render_default(default: ir.Default | None, required: bool) -> str:
    if default is not None:
        return literal(default.value)
    return "REQUIRED" if required else "UNSET"


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
"""Control characters that must not land raw in a docstring; \\n and \\t stay
literal (docstrings want them), \\r is escaped (source parsing would turn it
into a newline)."""


def docstring(text: str) -> str:
    """
    Escapes text for inclusion between triple quotes. Backslashes first, so a
    trailing backslash cannot swallow the closing quotes.
    """
    escaped = (
        text.replace("\\", "\\\\").replace('"""', r"\"\"\"").replace("'''", r"\'\'\'")
    )
    return _CONTROL_CHARS.sub(lambda m: f"\\x{ord(m.group()):02x}", escaped)


def is_plain_key(name: str) -> bool:
    """Whether a wire key can be a class-syntax TypedDict attribute."""
    return name.isidentifier() and not keyword.iskeyword(name)


def project_metadata(api: ir.Api) -> dict[str, str]:
    """pyproject.toml fields: a PEP 503-ish name, a one-line description."""
    name = re.sub(r"[^a-z0-9-]", "", api.title.lower().replace(" ", "-"))
    name = re.sub(r"-+", "-", name).strip("-")
    return {
        "project_name": name or "generated-client",
        "description": " ".join(api.description.split()) or "Generated Client",
        "version": api.version or "0.1.0",
    }


# ---------------------------------------------------------------------------
# Views: what the templates see
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldView:
    name: str
    annotation: str
    doc: str


@dataclass(frozen=True)
class ModelView:
    name: str
    doc: str
    functional: bool
    """Functional TypedDict syntax, needed when a wire key is not a plain
    identifier (``user-name``, ``class``)."""
    fields: tuple[FieldView, ...]


@dataclass(frozen=True)
class ArgView:
    name: str
    annotation: str
    default: str


@dataclass(frozen=True)
class OperationView:
    method: str
    path: str
    args: tuple[ArgView, ...]
    response: str
    doc: str
    locations: dict[str, dict[str, str]]
    """``{location: {python name: wire name}}``, empty locations omitted. Path
    names map to themselves: the path template already uses the Python names."""


def model_view(model: ir.Model, pending: frozenset[str]) -> ModelView:
    """
    :param pending: Models not yet defined at this point of the file (this
        one included). Class-syntax models never care (``from __future__
        import annotations`` makes their annotations lazy); functional ones
        are a call whose arguments are evaluated at import, so a reference
        to a pending model must be spelled as a string.
    """
    functional = not all(is_plain_key(f.name) for f in model.fields)
    return ModelView(
        name=model.name,
        doc=docstring(model.doc),
        functional=functional,
        fields=tuple(
            _field_view(f, forward_ref=functional and bool(ir.refs(f.type) & pending))
            for f in model.fields
        ),
    )


def _field_view(field: ir.Field, forward_ref: bool) -> FieldView:
    annotation = render_type(field.type)
    if not field.required:
        annotation = f"NotRequired[{annotation}]"
    if forward_ref:
        annotation = literal(annotation)

    lines = [field.doc] if field.doc else []
    if field.default is not None:
        lines.append(f"Server Default: {literal(field.default.value)}")
    if field.read_only:
        lines.append("[Read Only - Server generated]")
    if field.write_only:
        lines.append("[Write Only - Only used in requests]")
    return FieldView(field.name, annotation, docstring("\n".join(lines)))


def operation_view(op: ir.Operation) -> OperationView:
    return OperationView(
        method=op.method.value,
        path=op.path,
        args=_arguments(op),
        response=f"Response[{render_type(op.success)}, {render_type(op.error)}]",
        doc=docstring(op.doc or op.path),
        locations={
            loc.value: names
            for loc in ir.Location
            if (
                names := {
                    p.name: p.name if loc is ir.Location.PATH else p.api_name
                    for p in op.params
                    if p.location is loc
                }
            )
        },
    )


def _arguments(op: ir.Operation) -> tuple[ArgView, ...]:
    """Signature order: path params, body, then query/header/cookie params."""
    path_params = [p for p in op.params if p.location is ir.Location.PATH]
    others = [p for p in op.params if p.location is not ir.Location.PATH]

    args = [_param_arg(p) for p in path_params]
    if op.body:
        args.append(
            ArgView(
                op.body.slot.value,
                render_type(op.body.type),
                render_default(None, op.body.required),
            )
        )
    args += [_param_arg(p) for p in others]
    return tuple(args)


def _param_arg(param: ir.Param) -> ArgView:
    annotation = render_type(param.type)
    if wrapper := WRAPPERS.get(param.location):
        annotation = f"{wrapper}[{annotation}]"
    return ArgView(
        param.name, annotation, render_default(param.default, param.required)
    )


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


def emit(api: ir.Api, modes: Collection[Mode] = DEFAULT_MODES) -> dict[str, str]:
    """
    Renders the generated package as ``{filename: source}``.

    :param modes: Which client flavors to emit: any subset of ``MODES``
        (default: async only). Class names never change with the modes
        (``AsyncClient`` / ``Client``); the modes only control what is emitted.
    :raises GenerationError: if any emitted file would not compile.
    """
    chosen = _check_modes(modes)

    env = Environment(loader=FileSystemLoader(TEMPLATES), keep_trailing_newline=True)
    env.filters["py"] = literal

    # Dependencies first, so functional TypedDicts can use real annotations
    models = []
    pending = {m.name for m in api.models}
    for model in api.dependency_order():
        models.append(model_view(model, frozenset(pending)))
        pending.discard(model.name)

    context = {
        "metadata": project_metadata(api),
        "models": models,
        "operations": [operation_view(op) for op in api.operations],
        "methods": [m.value for m in ir.Method],
        "async_client": "async" in chosen,
        "sync_client": "sync" in chosen,
        "runtime_exports": runtime.__all__,
    }

    files = {
        Path(name).stem: env.get_template(name).render(context)
        for name in sorted(env.list_templates())
    }
    files["_runtime.py"] = Path(runtime.__file__).read_text(encoding="utf-8")

    for name, source in files.items():
        _validate(name, source)
    return files


def _check_modes(modes: Collection[Mode] | str) -> frozenset[Mode]:
    # A bare "sync" would otherwise iterate as characters
    requested: Collection[object] = (modes,) if isinstance(modes, str) else modes
    if not requested or any(m not in MODES for m in requested):
        raise GenerationError(
            f"Invalid client modes: {modes!r} (choose from {', '.join(MODES)})"
        )
    return frozenset(m for m in MODES if m in requested)


def _validate(name: str, source: str) -> None:
    """compile(), not ast.parse(): only the former catches duplicate arguments."""
    try:
        if name.endswith(".py"):
            compile(source, name, "exec")
        elif name.endswith(".toml"):
            tomllib.loads(source)
    except (SyntaxError, ValueError, tomllib.TOMLDecodeError) as e:
        raise GenerationError(
            f"Generated {name} is invalid ({e}). This is a bug in "
            "openapi-burrito or a hostile spec — no output was written."
        ) from e
