"""
openapi-burrito: a path-first, type-safe httpx client generator.

    doc = load("openapi.yaml")            # dict, external $refs resolved
    api = parse(doc)                      # ir.Api
    files = emit(api, modes=("async",))   # {"client.py": "...", ...}
    generate("openapi.yaml", "sdk/")      # all of the above, written and formatted

See docs/07-architecture.md.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from .emit import GenerationError, Mode, emit
from .generator import generate
from .spec import SpecError, load, parse

# Swallow logs unless the user configures a handler
logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = version("openapi-burrito")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "GenerationError",
    "Mode",
    "SpecError",
    "__version__",
    "emit",
    "generate",
    "load",
    "parse",
]
