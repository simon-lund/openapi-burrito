"""
Direct tests for the vendored runtime.

The runtime is a real module here and a verbatim copy in every generated
package, so it is tested like any other module — no generation needed.
``test_generation.py`` still drives it end-to-end through generated clients.
"""

import httpx
import pytest

from openapi_burrito.runtime import (
    REQUIRED,
    UNSET,
    Response,
    ResponseError,
    prepare_request,
)

LOCATIONS = {
    "path": {"pet_id": "pet_id"},
    "query": {"page_size": "pageSize"},
    "header": {"x_trace_id": "X-Trace-Id"},
    "cookie": {"session": "session"},
}


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(base_url="http://api.test")


class TestPrepareRequest:
    def test_routes_each_location(self, client: httpx.Client) -> None:
        req = prepare_request(
            client,
            "GET",
            "/pet/{pet_id}",
            params={
                "pet_id": 7,
                "page_size": 10,
                "x_trace_id": "abc",
                "session": "s1",
            },
            locations=LOCATIONS,
        )
        assert req.url.path == "/pet/7"
        assert req.url.params["pageSize"] == "10"
        assert req.headers["X-Trace-Id"] == "abc"
        assert req.headers["cookie"] == "session=s1"

    def test_unset_is_omitted_but_none_is_kept(self, client: httpx.Client) -> None:
        req = prepare_request(
            client,
            "GET",
            "/pet/{pet_id}",
            params={"pet_id": 1, "page_size": UNSET},
            locations=LOCATIONS,
        )
        assert "pageSize" not in req.url.params

        req = prepare_request(
            client,
            "GET",
            "/pet/{pet_id}",
            params={"pet_id": 1, "page_size": None},
            locations=LOCATIONS,
        )
        assert "pageSize" in req.url.params

    def test_required_sentinel_raises(self, client: httpx.Client) -> None:
        with pytest.raises(TypeError, match="Missing required parameter: pet_id"):
            prepare_request(
                client,
                "GET",
                "/pet/{pet_id}",
                params={"pet_id": REQUIRED},
                locations=LOCATIONS,
            )

    def test_unknown_param_raises(self, client: httpx.Client) -> None:
        with pytest.raises(TypeError, match="Unknown parameter"):
            prepare_request(
                client,
                "GET",
                "/pet/{pet_id}",
                params={"pet_id": 1, "nonsense": 5},
                locations=LOCATIONS,
            )

    def test_missing_path_param_raises(self, client: httpx.Client) -> None:
        with pytest.raises(TypeError, match="Missing required path parameter"):
            prepare_request(
                client, "GET", "/pet/{pet_id}", params={}, locations=LOCATIONS
            )

    def test_escape_hatch_without_locations(self, client: httpx.Client) -> None:
        """Unknown paths: placeholders from kwargs, the rest as query params."""
        req = prepare_request(
            client,
            "GET",
            "/not/in/spec/{thing_id}",
            params={"thing_id": 3, "q": "hello"},
            locations=None,
        )
        assert req.url.path == "/not/in/spec/3"
        assert req.url.params["q"] == "hello"

    def test_body_slots_forwarded(self, client: httpx.Client) -> None:
        req = prepare_request(
            client, "POST", "/pet", json={"name": "Rex"}, params={}, locations={}
        )
        assert req.read() == b'{"name":"Rex"}'

        req = prepare_request(
            client, "POST", "/upload", content=b"RAW", params={}, locations={}
        )
        assert req.read() == b"RAW"


class TestResponse:
    def test_json_success_body(self) -> None:
        res: Response[dict[str, int], None] = Response(
            httpx.Response(200, json={"id": 7})
        )
        assert res.is_success
        assert res.data == {"id": 7}
        assert res.error is None
        assert res.unwrap() == {"id": 7}

    def test_error_body(self) -> None:
        res: Response[None, dict[str, str]] = Response(
            httpx.Response(404, json={"message": "nope"})
        )
        assert res.data is None
        assert res.error == {"message": "nope"}
        with pytest.raises(ResponseError) as exc_info:
            res.unwrap()
        assert exc_info.value.response.status_code == 404

    def test_plus_json_and_ndjson(self) -> None:
        res: Response[object, object] = Response(
            httpx.Response(
                200,
                content=b'{"a": 1}',
                headers={"content-type": "application/vnd.api+json"},
            )
        )
        assert res.data == {"a": 1}

        res = Response(
            httpx.Response(
                200,
                content=b'{"a": 1}\n{"a": 2}\n',
                headers={"content-type": "application/x-ndjson"},
            )
        )
        assert res.data == [{"a": 1}, {"a": 2}]

    def test_non_json_and_malformed_fall_back_to_bytes(self) -> None:
        res: Response[object, object] = Response(
            httpx.Response(200, content=b"PNG", headers={"content-type": "image/png"})
        )
        assert res.data == b"PNG"

        res = Response(
            httpx.Response(
                200, content=b"not json {", headers={"content-type": "application/json"}
            )
        )
        assert res.data == b"not json {"

    def test_empty_body_is_none(self) -> None:
        res: Response[object, object] = Response(httpx.Response(204))
        assert res.data is None

    def test_passthrough_and_repr(self) -> None:
        res: Response[object, object] = Response(
            httpx.Response(
                200, headers={"x-id": "1"}, request=httpx.Request("GET", "/")
            )
        )
        assert res.headers["x-id"] == "1"
        assert res.url.path == "/"  # __getattr__ passthrough
        assert repr(res) == "<Response [200]>"
