"""
The frontend: OpenAPI document → ``ir.Api``.

This package knows OpenAPI — ``$ref``, ``allOf``, ``nullable``, content
types, parameter locations — and nothing about Python. Everything it
produces is an IR value; how that is spelled in Python is ``emit``'s job.
"""

from collections.abc import Mapping
from typing import Any

from .. import ir
from .guards import as_dict
from .load import SpecError, load
from .operations import operations
from .resolver import RefResolver
from .schemas import models

__all__ = ["SpecError", "load", "parse"]


def parse(spec: Mapping[str, Any]) -> ir.Api:
    """
    Builds the IR from a loaded OpenAPI document.

    :param spec: The document as returned by ``load`` (internal $refs intact).
    """
    resolver = RefResolver(spec)
    info = as_dict(spec.get("info"))
    return ir.Api(
        title=str(info.get("title") or ""),
        version=str(info.get("version") or ""),
        description=str(info.get("description") or ""),
        models=models(spec, resolver),
        operations=operations(spec, resolver),
    )
