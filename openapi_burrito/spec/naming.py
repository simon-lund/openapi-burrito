"""
Turning spec names into Python names.

Every identifier that ends up in generated code — model names, argument
names, path placeholders — passes through here. Specs are untrusted input, so
``identifier`` guarantees its result is a valid, non-keyword identifier or
raises; nothing downstream has to re-check.

See: CVE-2020-15142, GHSA-9x4c-63pf-525f
"""

import builtins
import keyword
import logging
import re
from collections.abc import Iterable, Mapping

from .. import ir

logger = logging.getLogger(__name__)

RESERVED_WORDS = (
    set(dir(builtins))  # list, dict, str, int, type, ...
    | {"self", "cls", "true", "false", "null", "undefined"}
) - {"id"}  # 'id' is ubiquitous in APIs; shadowing the builtin is the lesser evil

RESERVED_ARGUMENTS = frozenset({"self", "path", "json", "data", "files", "content"})
"""
Names the generated method signatures already use: ``self``, ``path``, and
the four request-body slots. A parameter may not take any of these.
"""


def identifier(value: str) -> str:
    """
    Converts an arbitrary string into a valid, non-keyword Python identifier.

    :raises ValueError: if nothing identifier-like is left (e.g. ``"!!!"``).
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")

    if not sanitized:
        raise ValueError(
            f"Cannot create identifier from empty or invalid value: {value!r}"
        )

    if sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    if keyword.iskeyword(sanitized) or sanitized in RESERVED_WORDS:
        sanitized = f"{sanitized}_"

    if not sanitized.isidentifier():  # cannot happen; belt and braces
        raise ValueError(
            f"Failed to create identifier from {value!r} (got {sanitized!r})"
        )
    return sanitized


def snake_case(name: str) -> str:
    """
    camelCase / PascalCase → snake_case, acronyms included
    (``HTTPResponse`` → ``http_response``, ``X_Trace_Id`` → ``x_trace_id``).
    """
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    return re.sub("_+", "_", s2)


def model_name(raw: str) -> str:
    """The Python class name for a ``components/schemas`` key."""
    return identifier(raw)


def argument_name(raw: str) -> str:
    """The Python argument name for a parameter name."""
    return snake_case(identifier(raw))


def deconflict(params: Iterable[ir.Param]) -> tuple[ir.Param, ...]:
    """
    Orders parameters by location and renames those whose Python name collides
    with a reserved argument or an earlier parameter (``pet_id`` → ``pet_id_query``).

    Path parameters come first, so they keep their natural names.
    """
    ordered = sorted(params, key=lambda p: list(ir.Location).index(p.location))
    taken = set(RESERVED_ARGUMENTS)
    result = []
    for param in ordered:
        name = param.name
        if name in taken:
            candidate = f"{name}_{param.location}"
            suffix = 2
            while candidate in taken:
                candidate = f"{name}_{param.location}{suffix}"
                suffix += 1
            logger.info("Renamed colliding argument %s to %s", name, candidate)
            param = ir.Param(
                candidate,
                param.api_name,
                param.location,
                param.type,
                param.required,
                param.default,
                param.doc,
            )
        taken.add(param.name)
        result.append(param)
    return tuple(result)


def rename_placeholders(path: str, names: Mapping[str, str]) -> str:
    """
    Rewrites ``{placeholders}`` in a path template to the parameters' Python
    names (``/pet/{petId}`` → ``/pet/{pet_id}``), so ``path.format(**kwargs)``
    lines up at runtime. Placeholders without a declared parameter are
    snake_cased.
    """

    def replace(m: re.Match[str]) -> str:
        return "{" + names.get(m.group(1), snake_case(m.group(1))) + "}"

    return re.sub(r"\{([^}]+)\}", replace, path)
