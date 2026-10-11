"""
End-to-end generation tests: generate real clients from fixture specs, import
them, and drive them through httpx.MockTransport.

These pin the contract between the emitter's templates and the vendored
runtime end to end — a template calling the runtime wrongly fails here instead
of in users' projects.
"""

import asyncio
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from openapi_burrito import GenerationError, generate


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
        # GET overrides the path-level str with int; once per client class
        # (sync + async). DELETE has no override, so it keeps the path-level
        # str — also once per class.
        assert client_src.count("user_id: int = REQUIRED") == 2
        assert client_src.count("user_id: str = REQUIRED") == 2

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
# Async client
# ---------------------------------------------------------------------------


class TestAsyncClient:
    def test_async_request(self, petstore: ModuleType) -> None:
        recorder = Recorder()

        async def flow() -> Any:
            api = petstore.AsyncClient(
                base_url="http://api.test", transport=httpx.MockTransport(recorder)
            )
            return await api.GET("/pet/{pet_id}", pet_id=7)

        res = asyncio.run(flow())
        assert recorder.last.url.path == "/pet/7"
        assert res.data == {"ok": True}

    def test_async_middleware_chain(self, petstore: ModuleType) -> None:
        recorder = Recorder()
        calls: list[str] = []

        async def flow() -> Any:
            api = petstore.AsyncClient(
                base_url="http://api.test", transport=httpx.MockTransport(recorder)
            )

            async def outer(request: httpx.Request, call_next: Any) -> httpx.Response:
                calls.append("before")
                response: httpx.Response = await call_next(request)
                calls.append("after")
                return response

            api.add_middleware(outer)
            return await api.POST("/pet", json={"name": "Rex"})

        res = asyncio.run(flow())
        assert res.status_code == 200
        assert calls == ["before", "after"]

    def test_async_body_sent(self, edge: ModuleType) -> None:
        recorder = Recorder(httpx.Response(204))

        async def flow() -> Any:
            api = edge.AsyncClient(
                base_url="http://api.test", transport=httpx.MockTransport(recorder)
            )
            return await api.DELETE("/users/{user_id}", user_id=1, json={"r": "x"})

        asyncio.run(flow())
        assert recorder.last.read() == b'{"r":"x"}'


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

    def test_unwrap_returns_typed_body(self, petstore: ModuleType) -> None:
        recorder = Recorder(httpx.Response(200, json={"id": 7, "name": "Rex"}))
        api = make_client(petstore, recorder)
        pet = api.GET("/pet/{pet_id}", pet_id=7).unwrap()
        assert pet == {"id": 7, "name": "Rex"}

    def test_unwrap_raises_on_error(self, petstore: ModuleType) -> None:
        recorder = Recorder(httpx.Response(404, json={"msg": "nope"}))
        api = make_client(petstore, recorder)
        with pytest.raises(petstore.ResponseError) as exc_info:
            api.GET("/pet/{pet_id}", pet_id=404).unwrap()
        assert exc_info.value.response.status_code == 404
        assert exc_info.value.response.error == {"msg": "nope"}

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
# Client modes
# ---------------------------------------------------------------------------


class TestClientModes:
    """--client controls what is emitted, never what a name means."""

    @pytest.mark.parametrize(
        ("modes", "expect_sync", "expect_async"),
        [
            (("async",), False, True),
            (("sync",), True, False),
            (("async", "sync"), True, True),
        ],
    )
    def test_modes_control_emitted_classes(
        self,
        tmp_path: Path,
        modes: tuple[str, ...],
        expect_sync: bool,
        expect_async: bool,
    ) -> None:
        out = tmp_path / f"client_{'_'.join(modes)}"
        generate(
            Path(__file__).parent / "fixtures" / "petstore.json",
            out,
            modes=modes,  # type: ignore[arg-type]
        )
        client_src = (out / "client.py").read_text()
        init_src = (out / "__init__.py").read_text()

        assert ("class Client:" in client_src) is expect_sync
        assert ("class AsyncClient:" in client_src) is expect_async
        assert ('"Client"' in init_src) is expect_sync
        assert ('"AsyncClient"' in init_src) is expect_async

    def test_invalid_modes_rejected(self, tmp_path: Path) -> None:
        spec = Path(__file__).parent / "fixtures" / "petstore.json"
        with pytest.raises(GenerationError, match="Invalid client modes"):
            generate(spec, tmp_path / "x", modes=())
        with pytest.raises(GenerationError, match="Invalid client modes"):
            generate(spec, tmp_path / "y", modes=("both",))  # type: ignore[arg-type]
        with pytest.raises(GenerationError, match="Invalid client modes"):
            # A bare string must not be iterated as characters
            generate(spec, tmp_path / "z", modes="both")  # type: ignore[arg-type]
        with pytest.raises(GenerationError, match="Invalid client modes"):
            # The error path itself must not crash on unorderable input
            generate(spec, tmp_path / "w", modes=("async", 3))  # type: ignore[arg-type]

    def test_bare_string_mode_is_accepted(self, tmp_path: Path) -> None:
        spec = Path(__file__).parent / "fixtures" / "petstore.json"
        out = tmp_path / "client_sync"
        generate(spec, out, modes="sync")  # type: ignore[arg-type]
        assert "class Client:" in (out / "client.py").read_text()

    def test_default_mode_is_async(self, tmp_path: Path) -> None:
        out = tmp_path / "client_default"
        generate(Path(__file__).parent / "fixtures" / "petstore.json", out)
        client_src = (out / "client.py").read_text()
        assert "class AsyncClient:" in client_src
        assert "class Client:" not in client_src


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
