"""Shared fixtures: generate client packages from fixture specs once per session."""

import importlib
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

from openapi_burrito.generator import generate_sdk

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def generated_client(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Callable[[str], ModuleType]]:
    """
    Returns a loader: spec fixture name -> imported generated client package.

    Generation and import happen once per spec per test session.
    """
    root = tmp_path_factory.mktemp("generated")
    sys.path.insert(0, str(root))
    packages: dict[str, ModuleType] = {}

    def _load(spec_name: str) -> ModuleType:
        package = f"{spec_name}_client"
        if package not in packages:
            # Both flavors so the suite can exercise sync and async surfaces
            generate_sdk(
                FIXTURES / f"{spec_name}.json",
                root / package,
                client_modes=("async", "sync"),
            )
            packages[package] = importlib.import_module(package)
        return packages[package]

    yield _load

    sys.path.remove(str(root))
    for package in packages:
        for module in [m for m in sys.modules if m.split(".")[0] == package]:
            del sys.modules[module]
