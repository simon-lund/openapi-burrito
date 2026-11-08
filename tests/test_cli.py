"""The CLI, driven through typer's test runner."""

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openapi_burrito.cli import app

PETSTORE = Path(__file__).parent / "fixtures" / "petstore.json"
runner = CliRunner()


class TestGenerate:
    def test_generates_a_package(self, tmp_path: Path) -> None:
        out = tmp_path / "sdk"
        result = runner.invoke(
            app, ["generate", str(PETSTORE), "-o", str(out), "-y", "-c", "sync"]
        )
        assert result.exit_code == 0, result.output
        assert "Successfully generated" in result.output
        assert {p.name for p in out.iterdir()} == {
            "__init__.py",
            "_runtime.py",
            "client.py",
            "models.py",
            "pyproject.toml",
        }
        assert "class Client:" in (out / "client.py").read_text()

    def test_external_ref_needs_the_flag(self, tmp_path: Path) -> None:
        (tmp_path / "outside.json").write_text('{"type": "object"}')
        spec = tmp_path / "api" / "openapi.json"
        spec.parent.mkdir()
        spec.write_text(
            json.dumps(
                {
                    "openapi": "3.0.3",
                    "info": {"title": "t", "version": "1"},
                    "paths": {},
                    "components": {"schemas": {"M": {"$ref": "../outside.json"}}},
                }
            )
        )
        out = tmp_path / "sdk"
        args = ["generate", str(spec), "-o", str(out), "-y"]

        refused = runner.invoke(app, args)
        assert refused.exit_code == 1
        assert "--allow-external-refs" in " ".join(refused.output.split())
        assert not out.exists()

        allowed = runner.invoke(app, [*args, "--allow-external-refs"])
        assert allowed.exit_code == 0, allowed.output
        assert "class M(" in (out / "models.py").read_text()

    def test_repeatable_client_flag(self, tmp_path: Path) -> None:
        out = tmp_path / "sdk"
        args = ["generate", str(PETSTORE), "-o", str(out), "-y"]
        args += ["-c", "async", "-c", "sync"]
        assert runner.invoke(app, args).exit_code == 0
        client = (out / "client.py").read_text()
        assert "class Client:" in client
        assert "class AsyncClient:" in client

    def test_security_prompt_can_abort(self, tmp_path: Path) -> None:
        out = tmp_path / "sdk"
        args = ["generate", str(PETSTORE), "-o", str(out)]
        result = runner.invoke(app, args, input="n\n")
        assert result.exit_code != 0
        assert "Security Notice" in result.output
        assert not out.exists()

    def test_failure_is_reported_not_raised(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["generate", str(tmp_path / "missing.json"), "-o", str(tmp_path), "-y"]
        )
        assert result.exit_code == 1
        assert "Error" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


class TestPreview:
    def test_missing_extra_gives_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without the 'preview' extra the command explains how to install it —
        and importing the module itself must not be what fails."""
        import openapi_burrito.preview  # noqa: F401 - importable without the extra

        monkeypatch.setitem(sys.modules, "fastapi", None)  # makes `import fastapi` fail
        result = runner.invoke(app, ["preview", str(PETSTORE)])
        assert result.exit_code == 1
        assert "Preview dependencies missing" in result.output
        assert "openapi-burrito[preview]" in result.output
