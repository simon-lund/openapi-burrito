"""The CLI, driven through typer's test runner."""

from pathlib import Path

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
