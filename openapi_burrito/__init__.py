import logging
from importlib.metadata import PackageNotFoundError, version

# Swallow logs unless the user configures a handler
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Dynamic versioning
try:
    __version__ = version("openapi-burrito")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = ["__version__"]
