"""
End-to-end generation tests: generate real clients from fixture specs, import
them, and drive them through httpx.MockTransport.

These pin the contract between the parser, the templates, and the generated
runtime — template drift (e.g. a constructor changing in models.py.jinja2 but
not client.py.jinja2) fails here instead of in users' projects.
"""

import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest


def source_dir(module: ModuleType) -> Path:
    """Directory the generated package was written to."""
    assert module.__file__ is not None
    return Path(module.__file__).parent


class Recorder:
    """MockTransport handler that records requests and replays a response."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json={"ok": True})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def petstore(generated_client: Callable[[str], ModuleType]) -> ModuleType:
    return generated_client("petstore")


@pytest.fixture
def edge(generated_client: Callable[[str], ModuleType]) -> ModuleType:
    return generated_client("edgecases")


def make_client(module: ModuleType, recorder: Recorder) -> Any:
    return module.Client(
        base_url="http://api.test", transport=httpx.MockTransport(recorder)
    )


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


class TestRequestBuilding:
    def test_path_param_substitution(self, petstore: ModuleType) -> None:
        recorder = Recorder()
        api = make_client(petstore, recorder)
        res = api.GET("/pet/{pet_id}", pet_id=7)
        assert recorder.last.url.path == "/pet/7"
        assert res.status_code == 200
        assert res.data == {"ok": True}

    def test_query_params_mapped_to_api_names(self, petstore: ModuleType) -> None:
        recorder = Recorder()
        api = make_client(petstore, recorder)
        api.POST(
            "/pet/{pet_id}/uploadImage",
            pet_id=1,
            additional_metadata="meta",
            content=b"IMG",
        )
        # snake_case argument maps back to the original camelCase name
        assert recorder.last.url.params["additionalMetadata"] == "meta"

    def test_header_params_mapped(self, edge: ModuleType) -> None:
        recorder = Recorder()
        api = make_client(edge, recorder)
        api.GET("/users/{user_id}", user_id=1, x_trace_id="abc")
        assert recorder.last.headers["X-Trace-Id"] == "abc"

    def test_json_body_sent(self, petstore: ModuleType) -> None:
        recorder = Recorder()
        api = make_client(petstore, recorder)
        api.POST("/pet", json={"name": "Rex"})
        assert recorder.last.read() == b'{"name":"Rex"}'

    def test_octet_stream_body_sent(self, petstore: ModuleType) -> None:
        """Regression: raw 'content' bodies used to be silently dropped."""
        recorder = Recorder()
        api = make_client(petstore, recorder)
        api.POST("/pet/{pet_id}/uploadImage", pet_id=1, content=b"IMAGE_BYTES")
        assert recorder.last.read() == b"IMAGE_BYTES"

    def test_delete_with_json_body_sent(self, edge: ModuleType) -> None:
        """Regression: bodies on methods without body args used to vanish."""
        recorder = Recorder(httpx.Response(204))
        api = make_client(edge, recorder)
        api.DELETE("/users/{user_id}", user_id=1, json={"reason": "spam"})
        assert recorder.last.read() == b'{"reason":"spam"}'

    def test_unset_params_omitted(self, petstore: ModuleType) -> None:
        recorder = Recorder()
        api = make_client(petstore, recorder)
        api.GET("/user/login")
        assert "username" not in recorder.last.url.params
        assert "password" not in recorder.last.url.params

    def test_required_sentinel_raises(self, petstore: ModuleType) -> None:
        api = make_client(petstore, Recorder())
        with pytest.raises(TypeError, match="Missing required parameter"):
            api.GET("/pet/{pet_id}", pet_id=petstore.REQUIRED)

    def test_unknown_param_raises(self, petstore: ModuleType) -> None:
        api = make_client(petstore, Recorder())
        with pytest.raises(TypeError, match="Unknown parameter"):
            api.GET("/pet/{pet_id}", pet_id=1, nonsense=5)

    def test_unknown_path_escape_hatch(self, petstore: ModuleType) -> None:
        """Paths not in the spec still work: kwargs become path/query params."""
        recorder = Recorder()
        api = make_client(petstore, recorder)
        api.GET("/not/in/spec/{thing_id}", thing_id=3, q="hello")
        assert recorder.last.url.path == "/not/in/spec/3"
        assert recorder.last.url.params["q"] == "hello"


# ---------------------------------------------------------------------------
# Parameter collisions & dedup
# ---------------------------------------------------------------------------


class TestCollisions:
    def test_path_level_param_override_deduped(self, edge: ModuleType) -> None:
        """Operation-level params override path-level ones (spec rule).

        Used to render duplicate function args -> SyntaxError on import.
        The import in the fixture already proves it compiles; check the
        override picked the operation-level type.
        """
        client_src = (source_dir(edge) / "client.py").read_text()
        assert client_src.count("user_id: int = REQUIRED") == 1

    def test_snake_case_collision_renamed(self, edge: ModuleType) -> None:
        recorder = Recorder()
        api = make_client(edge, recorder)
        # petId and pet_id both snake_case to pet_id; second one got a suffix
        api.GET("/search", pet_id=1, pet_id_query="two")
        assert recorder.last.url.params["petId"] == "1"
        assert recorder.last.url.params["pet_id"] == "two"

    def test_param_colliding_with_body_slot_renamed(self, edge: ModuleType) -> None:
        """A query param named 'json' must not shadow the json body slot."""
        recorder = Recorder()
        api = make_client(edge, recorder)
        api.GET("/search", json_query="q")
        assert recorder.last.url.params["json"] == "q"
        assert recorder.last.read() == b""  # nothing leaked into the body


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


class TestResponse:
    def test_error_body_parsed(self, edge: ModuleType) -> None:
        recorder = Recorder(httpx.Response(404, json={"message": "nope"}))
        api = make_client(edge, recorder)
        res = api.GET("/users/{user_id}", user_id=1)
        assert res.data is None
        assert res.error == {"message": "nope"}
        assert res.is_error

    def test_no_content_response(self, edge: ModuleType) -> None:
        recorder = Recorder(httpx.Response(204))
        api = make_client(edge, recorder)
        res = api.DELETE("/users/{user_id}", user_id=1, json={})
        assert res.status_code == 204
        assert res.data is None

    def test_plus_json_content_type_parsed(self, edge: ModuleType) -> None:
        recorder = Recorder(
            httpx.Response(
                200,
                content=b'{"name": "root"}',
                headers={"content-type": "application/vnd.api+json"},
            )
        )
        api = make_client(edge, recorder)
        res = api.GET("/search")
        assert res.data == {"name": "root"}

    def test_malformed_json_falls_back_to_bytes(self, petstore: ModuleType) -> None:
        recorder = Recorder(
            httpx.Response(
                200,
                content=b"not json {",
                headers={"content-type": "application/json"},
            )
        )
        api = make_client(petstore, recorder)
        res = api.GET("/pet/{pet_id}", pet_id=1)
        assert res.data == b"not json {"


# ---------------------------------------------------------------------------
# Generated models
# ---------------------------------------------------------------------------


class TestModels:
    def test_wire_format_keys_preserved(self, edge: ModuleType) -> None:
        """TypedDict keys must match the JSON on the wire — never renamed."""
        annotations = edge.models.User.__annotations__
        assert {"id", "type", "user-name", "class"} <= set(annotations)

    def test_recursive_model(self, edge: ModuleType) -> None:
        annotations = edge.models.Tree.__annotations__
        assert "children" in annotations

    def test_all_of_flattened(self, edge: ModuleType) -> None:
        annotations = edge.models.Admin.__annotations__
        assert {"message", "level"} <= set(annotations)

    def test_ref_response_types_use_model_name(self, edge: ModuleType) -> None:
        client_src = (source_dir(edge) / "client.py").read_text()
        # $ref'd parameter and response resolve to the page param + User model
        assert "Response[User, Any]" in client_src
        assert "page: Query[int] = 1" in client_src


# ---------------------------------------------------------------------------
# Type-check the generated output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_name", ["petstore", "edgecases"])
def test_generated_client_passes_strict_mypy(
    generated_client: Callable[[str], ModuleType], spec_name: str
) -> None:
    """The typed surface is the product — the output must be strict-clean."""
    module = generated_client(spec_name)
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--no-error-summary", "."],
        cwd=source_dir(module),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"mypy --strict failed:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_pyproject_valid_and_escaped(self, edge: ModuleType) -> None:
        data = tomllib.loads((source_dir(edge) / "pyproject.toml").read_text())
        assert data["project"]["version"] == "2.3.4"
        # Quotes and backslashes in the spec description survive TOML-escaping
        assert '"quotes"' in data["project"]["description"]
        assert "\\" in data["project"]["description"]
