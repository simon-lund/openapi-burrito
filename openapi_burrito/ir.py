"""
The intermediate representation: what an API *is*, independent of how OpenAPI
spells it (``spec/``) and how Python will spell it (``emit/``).

Everything here is a frozen value. Two nodes are equal when they describe the
same thing; nothing is compared by identity. Models are referenced by name
(``Ref("Pet")``) and looked up in ``Api.models`` — the reference graph is
computed on demand (``refs``, ``Api.dependencies``), never stored as object
pointers. See docs/07-architecture.md, "Tree or graph?".
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
"""A JSON value, as it appears in ``default`` and ``enum``."""

# ---------------------------------------------------------------------------
# Type expressions: what a JSON value may be
# ---------------------------------------------------------------------------

type PrimitiveKind = Literal["string", "integer", "number", "boolean", "binary", "null"]


@dataclass(frozen=True, slots=True)
class Primitive:
    kind: PrimitiveKind


@dataclass(frozen=True, slots=True)
class Any:
    """The ``true`` schema: any value is valid."""


@dataclass(frozen=True, slots=True)
class Never:
    """The ``false`` schema: no value is valid."""


@dataclass(frozen=True, slots=True)
class Ref:
    """A named model, by name. Resolve with ``Api.model(name)``."""

    name: str


@dataclass(frozen=True, slots=True)
class Array:
    item: TypeExpr


@dataclass(frozen=True, slots=True)
class Map:
    """An object with ``additionalProperties``: string keys, ``value`` values."""

    value: TypeExpr


@dataclass(frozen=True, slots=True)
class Union:
    """
    One of several types. Build with ``union()``, which normalizes; a ``Union``
    constructed directly is taken as-is.
    """

    members: tuple[TypeExpr, ...]


type EnumValue = str | int | bool | None
"""The JSON values that can be spelled as a Python ``Literal``."""


@dataclass(frozen=True, slots=True)
class Enum:
    """A JSON-schema ``enum``. Floats, arrays and objects are rejected: there is
    no ``Literal[1.5]``."""

    values: tuple[EnumValue, ...]

    def __post_init__(self) -> None:
        for value in self.values:
            if not isinstance(value, str | int | bool | None):
                raise TypeError(f"Enum value {value!r} cannot be a Literal")


type TypeExpr = Primitive | Any | Never | Ref | Array | Map | Union | Enum

STRING = Primitive("string")
INTEGER = Primitive("integer")
NUMBER = Primitive("number")
BOOLEAN = Primitive("boolean")
BINARY = Primitive("binary")
NULL = Primitive("null")
ANY = Any()
NEVER = Never()


def union(*members: TypeExpr) -> TypeExpr:
    """
    The normalizing constructor for unions.

    Flattens nested unions, drops ``Never``, merges enums, dedupes, and
    returns the single member (or ``ANY`` for none) instead of a one-member
    union. ``Any`` absorbs everything. Member order is canonical, so
    ``union(a, b) == union(b, a)``.
    """
    flat: list[TypeExpr] = []
    enum_values: list[EnumValue] = []
    for member in members:
        match member:
            case Union(inner):
                flat.extend(inner)
            case Any():
                return ANY
            case Never():
                continue
            case Enum(values):
                enum_values.extend(v for v in values if v not in enum_values)
            case _:
                flat.append(member)

    if any(isinstance(m, Any) for m in flat):
        return ANY
    if enum_values:
        flat.append(Enum(tuple(enum_values)))

    unique = sorted(set(flat), key=repr)
    if not unique:
        return ANY
    if len(unique) == 1:
        return unique[0]
    return Union(tuple(unique))


def walk(expr: TypeExpr) -> Iterator[TypeExpr]:
    """Yields ``expr`` and every type expression nested inside it."""
    yield expr
    match expr:
        case Array(item) | Map(item):
            yield from walk(item)
        case Union(members):
            for member in members:
                yield from walk(member)
        case _:
            pass


def refs(expr: TypeExpr) -> frozenset[str]:
    """The names of all models ``expr`` references, at any depth."""
    return frozenset(node.name for node in walk(expr) if isinstance(node, Ref))


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Default:
    """A default value. ``Default(None)`` is "defaults to null"; a missing
    default is spelled ``None`` on the owning node."""

    value: Json


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    """The wire key, verbatim. TypedDict keys must match the JSON."""
    type: TypeExpr
    required: bool
    doc: str = ""
    default: Default | None = None
    read_only: bool = False
    write_only: bool = False


@dataclass(frozen=True, slots=True)
class Model:
    name: str
    """A valid Python identifier."""
    fields: tuple[Field, ...]
    doc: str = ""

    def refs(self) -> frozenset[str]:
        """Models this model references directly through its fields."""
        return frozenset().union(*(refs(f.type) for f in self.fields))


class Location(StrEnum):
    """Where a parameter travels. Declaration order is signature order."""

    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"


class Slot(StrEnum):
    """The httpx keyword a request body is passed through."""

    JSON = "json"
    DATA = "data"
    FILES = "files"
    CONTENT = "content"


class Method(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    """The Python argument name."""
    api_name: str
    """The name on the wire."""
    location: Location
    type: TypeExpr
    required: bool
    default: Default | None = None
    doc: str = ""


@dataclass(frozen=True, slots=True)
class Body:
    slot: Slot
    type: TypeExpr
    required: bool
    doc: str = ""


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    type: TypeExpr
    """``NULL`` for a response without a body."""


@dataclass(frozen=True, slots=True)
class Operation:
    method: Method
    path: str
    """The path template, with ``{placeholders}`` named after the path params'
    Python names."""
    params: tuple[Param, ...] = ()
    body: Body | None = None
    responses: tuple[Response, ...] = ()
    doc: str = ""
    tags: tuple[str, ...] = ()
    operation_id: str | None = None

    @property
    def success(self) -> TypeExpr:
        """The union of all 2xx response types (``ANY`` if there are none)."""
        return union(*(r.type for r in self.responses if 200 <= r.status < 300))

    @property
    def error(self) -> TypeExpr:
        """The union of all 4xx/5xx response types (``ANY`` if there are none)."""
        return union(*(r.type for r in self.responses if 400 <= r.status < 600))

    def refs(self) -> frozenset[str]:
        """Models this operation references through params, body or responses."""
        exprs = [p.type for p in self.params] + [r.type for r in self.responses]
        if self.body:
            exprs.append(self.body.type)
        return frozenset().union(*(refs(e) for e in exprs))


@dataclass(frozen=True, slots=True)
class Api:
    title: str
    version: str
    description: str
    models: tuple[Model, ...]
    """In spec order."""
    operations: tuple[Operation, ...]
    """In spec order."""

    def model(self, name: str) -> Model:
        """Resolves a ``Ref`` by name."""
        for model in self.models:
            if model.name == name:
                return model
        raise KeyError(name)

    def dependencies(self) -> dict[str, frozenset[str]]:
        """The model reference graph: ``{model: models it references}``."""
        return {m.name: m.refs() for m in self.models}

    def dependency_order(self) -> tuple[Model, ...]:
        """
        Models with their dependencies first; spec order breaks ties.

        A cycle (``Tree → Tree``, ``User ↔ Pet``) cannot be ordered: its
        members keep spec order, and whoever consumes this must treat a
        reference to a later model as a forward reference.
        """
        names = {m.name for m in self.models}
        deps = {m.name: (m.refs() & names) - {m.name} for m in self.models}
        pending = list(self.models)
        done: set[str] = set()
        ordered: list[Model] = []
        while pending:
            ready = next(
                (m for m in pending if deps[m.name] <= done),
                pending[0],  # cycle: break it at the earliest model in spec order
            )
            pending.remove(ready)
            done.add(ready.name)
            ordered.append(ready)
        return tuple(ordered)
