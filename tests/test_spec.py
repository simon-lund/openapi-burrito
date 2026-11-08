"""Tests for the frontend: naming, $ref resolution, type reading, parse()."""

import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from openapi_burrito import ir
from openapi_burrito.ir import (
    ANY,
    BINARY,
    INTEGER,
    NEVER,
    NULL,
    STRING,
    Array,
    Enum,
    Map,
    Ref,
)
from openapi_burrito.spec import SpecError, load, naming, parse
from openapi_burrito.spec.resolver import RefResolver
from openapi_burrito.spec.types import type_expr

FIXTURES = Path(__file__).parent / "fixtures"


def read(schema: Any, schemas: dict[str, Any] | None = None) -> ir.TypeExpr:
    return type_expr(schema, RefResolver({"components": {"schemas": schemas or {}}}))


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------


class TestIdentifier:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("User", "User"),
            ("user-profile", "user_profile"),
            ("user profile", "user_profile"),
            ("123abc", "_123abc"),
            ("class", "class_"),
            ("return", "return_"),
            ("list", "list_"),
            ("type", "type_"),
            ("id", "id"),
            (
                "User:\n    pass\nimport os; os.system('rm -rf /')  # ",
                "User_pass_import_os_os_system_rm_rf",
            ),
        ],
    )
    def test_cases(self, raw: str, expected: str) -> None:
        assert naming.identifier(raw) == expected

    @pytest.mark.parametrize("raw", ["!!!", "@#$%", "---", ""])
    def test_nothing_left_raises(self, raw: str) -> None:
        with pytest.raises(ValueError, match="empty or invalid"):
            naming.identifier(raw)


class TestSnakeCase:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("camelCase", "camel_case"),
            ("PascalCase", "pascal_case"),
            ("HTTPResponse", "http_response"),
            ("X_Trace_Id", "x_trace_id"),
            ("already_snake", "already_snake"),
        ],
    )
    def test_cases(self, raw: str, expected: str) -> None:
        assert naming.snake_case(raw) == expected

    def test_argument_name_composes(self) -> None:
        assert naming.argument_name("X-Trace-Id") == "x_trace_id"
        assert naming.argument_name("petId") == "pet_id"


def param(name: str, location: ir.Location, api_name: str | None = None) -> ir.Param:
    return ir.Param(name, api_name or name, location, STRING, required=False)


class TestArgumentName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("petId", "pet_id"),
            ("From", "from_"),
            ("Class", "class_"),
            ("IN", "in_"),
            ("from", "from_"),
        ],
    )
    def test_never_a_keyword(self, raw: str, expected: str) -> None:
        assert naming.argument_name(raw) == expected


class TestDeconflict:
    def test_orders_by_location(self) -> None:
        params = naming.deconflict(
            [
                param("c", ir.Location.COOKIE),
                param("q", ir.Location.QUERY),
                param("p", ir.Location.PATH),
                param("h", ir.Location.HEADER),
            ]
        )
        assert [p.name for p in params] == ["p", "q", "h", "c"]

    def test_reserved_and_duplicate_names_get_location_suffix(self) -> None:
        params = naming.deconflict(
            [
                param("json", ir.Location.QUERY),
                param("pet_id", ir.Location.QUERY, "petId"),
                param("pet_id", ir.Location.QUERY),
                param("pet_id", ir.Location.HEADER),
            ]
        )
        assert [p.name for p in params] == [
            "json_query",
            "pet_id",
            "pet_id_query",
            "pet_id_header",
        ]
        assert [p.api_name for p in params] == ["json", "petId", "pet_id", "pet_id"]

    def test_path_params_keep_their_names(self) -> None:
        params = naming.deconflict(
            [param("pet_id", ir.Location.QUERY), param("pet_id", ir.Location.PATH)]
        )
        assert [p.name for p in params] == ["pet_id", "pet_id_query"]


class TestRenamePlaceholders:
    def test_uses_python_names(self) -> None:
        assert naming.rename_placeholders("/pet/{petId}", {"petId": "pet_id_path"}) == (
            "/pet/{pet_id_path}"
        )

    def test_undeclared_placeholder_is_snake_cased(self) -> None:
        assert naming.rename_placeholders("/pet/{petId}/{x}", {}) == "/pet/{pet_id}/{x}"


# ---------------------------------------------------------------------------
# resolver
# ---------------------------------------------------------------------------


class TestRefResolver:
    def test_schema_name_is_raw(self) -> None:
        resolver = RefResolver({})
        assert resolver.schema_name("#/components/schemas/Pet") == "Pet"
        assert resolver.schema_name("#/components/schemas/my-pet") == "my-pet"
        assert resolver.schema_name("#/components/schemas/a~1b") == "a/b"

    def test_schema_name_rejects_non_models(self) -> None:
        resolver = RefResolver({})
        assert resolver.schema_name("#/components/schemas/Pet/properties/id") is None
        assert resolver.schema_name("#/components/parameters/Page") is None
        assert resolver.schema_name(None) is None

    def test_deref_follows_chain(self) -> None:
        resolver = RefResolver(
            {
                "components": {
                    "schemas": {
                        "A": {"$ref": "#/components/schemas/B"},
                        "B": {"type": "string"},
                    }
                }
            }
        )
        assert resolver.deref({"$ref": "#/components/schemas/A"}) == {"type": "string"}

    def test_deref_passthrough(self) -> None:
        resolver = RefResolver({})
        assert resolver.deref({"type": "integer"}) == {"type": "integer"}
        assert resolver.deref(None) is None

    def test_deref_broken_and_circular_refs_are_empty(self) -> None:
        resolver = RefResolver(
            {
                "components": {
                    "schemas": {
                        "A": {"$ref": "#/components/schemas/B"},
                        "B": {"$ref": "#/components/schemas/A"},
                    }
                }
            }
        )
        assert resolver.deref({"$ref": "#/components/schemas/A"}) == {}
        assert resolver.deref({"$ref": "#/components/schemas/Nope"}) == {}
        assert resolver.deref({"$ref": "other.yaml#/X"}) == {}


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


def spec_with_models(**schemas: Any) -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {"schemas": schemas},
    }


def write(path: Path, document: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    return path


class SpecServer:
    """A local HTTP server for specs and ref targets; records what was requested."""

    def __init__(self) -> None:
        self.documents: dict[str, Any] = {}
        self.requests: list[str] = []
        self.url = ""


@pytest.fixture
def server() -> Iterator[SpecServer]:
    state = SpecServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append(self.path)
            body = json.dumps(state.documents[self.path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as http:
        Thread(target=http.serve_forever, daemon=True).start()
        state.url = f"http://127.0.0.1:{http.server_address[1]}"
        yield state
        http.shutdown()


class TestExternalRefs:
    SECRET = {"type": "object", "description": "secret"}  # noqa: RUF012

    @pytest.fixture
    def folder(self, tmp_path: Path) -> Path:
        """The spec's folder; ``tmp_path/outside`` holds a file it must not reach."""
        write(tmp_path / "outside" / "secret.json", self.SECRET)
        return tmp_path / "api"

    def test_files_inside_the_folder_are_resolved(self, folder: Path) -> None:
        write(folder / "models" / "pet.json", {"$ref": "owner.json"})
        write(folder / "models" / "owner.json", {"type": "object", "description": "o"})
        spec = spec_with_models(Pet={"$ref": "models/pet.json"})

        loaded = load(write(folder / "openapi.json", spec))

        assert loaded["components"]["schemas"]["Pet"]["description"] == "o"

    @pytest.mark.parametrize(
        "ref",
        [
            "../outside/secret.json",
            "file://{root}/outside/secret.json",
            "{root}/outside/secret.json",
            "models/../../outside/secret.json",
            "python://prance/__init__.py",
        ],
    )
    def test_anything_else_on_disk_is_refused(self, folder: Path, ref: str) -> None:
        spec = spec_with_models(M={"$ref": ref.format(root=folder.parent)})
        with pytest.raises(SpecError, match="external"):
            load(write(folder / "openapi.json", spec))

    def test_refused_before_it_is_read(self, folder: Path) -> None:
        """A read would fail with "file not found" instead."""
        spec = spec_with_models(M={"$ref": "../outside/missing.json"})
        with pytest.raises(SpecError, match="external"):
            load(write(folder / "openapi.json", spec))

    def test_refused_when_a_file_inside_leads_outside(self, folder: Path) -> None:
        write(folder / "hop.json", {"$ref": "../outside/secret.json"})
        spec = spec_with_models(M={"$ref": "hop.json"})
        with pytest.raises(SpecError, match="external"):
            load(write(folder / "openapi.json", spec))

    def test_refused_when_a_symlink_leads_outside(self, folder: Path) -> None:
        folder.mkdir()
        (folder / "link.json").symlink_to(folder.parent / "outside" / "secret.json")
        spec = spec_with_models(M={"$ref": "link.json"})
        with pytest.raises(SpecError, match="external"):
            load(write(folder / "openapi.json", spec))

    def test_outside_refs_anywhere_in_the_document(self, folder: Path) -> None:
        spec = spec_with_models()
        spec["info"]["description"] = {"$ref": "../outside/secret.json#/description"}
        with pytest.raises(SpecError, match="external"):
            load(write(folder / "openapi.json", spec))

    def test_url_refused_without_a_request(
        self, folder: Path, server: SpecServer
    ) -> None:
        server.documents["/secret.json"] = self.SECRET
        spec = spec_with_models(M={"$ref": f"{server.url}/secret.json"})
        with pytest.raises(SpecError, match="external"):
            load(write(folder / "openapi.json", spec))
        assert server.requests == []

    def test_spec_from_url_keeps_internal_refs(self, server: SpecServer) -> None:
        server.documents["/openapi.json"] = spec_with_models(
            A={"type": "object"}, B={"$ref": "#/components/schemas/A"}
        )
        loaded = load(f"{server.url}/openapi.json")
        assert loaded["components"]["schemas"]["B"] == {
            "$ref": "#/components/schemas/A"
        }

    def test_spec_from_url_cannot_read_local_files(
        self, folder: Path, server: SpecServer
    ) -> None:
        server.documents["/openapi.json"] = spec_with_models(
            M={"$ref": f"file://{folder.parent}/outside/secret.json"}
        )
        with pytest.raises(SpecError, match="external"):
            load(f"{server.url}/openapi.json")

    def test_spec_from_url_cannot_reach_other_urls(self, server: SpecServer) -> None:
        server.documents["/openapi.json"] = spec_with_models(
            M={"$ref": f"{server.url}/secret.json"}
        )
        with pytest.raises(SpecError, match="external"):
            load(f"{server.url}/openapi.json")
        assert server.requests == ["/openapi.json"]

    def test_opt_in_allows_both(self, folder: Path, server: SpecServer) -> None:
        server.documents["/remote.json"] = {"type": "object", "description": "remote"}
        spec = spec_with_models(
            Local={"$ref": "../outside/secret.json"},
            Remote={"$ref": f"{server.url}/remote.json"},
        )
        source = write(folder / "openapi.json", spec)

        schemas = load(source, allow_external_refs=True)["components"]["schemas"]

        assert schemas["Local"]["description"] == "secret"
        assert schemas["Remote"]["description"] == "remote"


class TestTypeExpr:
    def test_ref_becomes_named_model(self) -> None:
        assert read({"$ref": "#/components/schemas/my-pet"}, {"my-pet": {}}) == Ref(
            "my_pet"
        )

    def test_ref_to_non_schema_is_inlined(self) -> None:
        spec = {"components": {"parameters": {"P": {"type": "integer"}}}}
        assert (
            type_expr({"$ref": "#/components/parameters/P"}, RefResolver(spec))
            == INTEGER
        )

    def test_nullable_is_a_union_with_null(self) -> None:
        assert read({"$ref": "#/components/schemas/Pet", "nullable": True}) == ir.union(
            Ref("Pet"), NULL
        )
        assert read({"type": ["string", "null"]}) == ir.union(STRING, NULL)
        assert read({"oneOf": [{"type": "string"}, {"type": "null"}]}) == ir.union(
            STRING, NULL
        )

    def test_nullable_does_not_double_up(self) -> None:
        assert read({"type": ["string", "null"], "nullable": True}) == ir.union(
            STRING, NULL
        )

    def test_composition(self) -> None:
        assert read({"anyOf": [{"type": "string"}, {"type": "integer"}]}) == ir.union(
            STRING, INTEGER
        )
        assert read({"allOf": [{"$ref": "#/components/schemas/Pet"}]}) == Ref("Pet")
        assert read({"allOf": [{"type": "string"}, {"type": "integer"}]}) == ANY

    def test_containers(self) -> None:
        assert read({"type": "array", "items": {"type": "string"}}) == Array(STRING)
        assert read({"type": "array"}) == Array(ANY)
        assert read({"items": {"$ref": "#/components/schemas/Node"}}) == Array(
            Ref("Node")
        )
        assert read(
            {"type": "object", "additionalProperties": {"type": "integer"}}
        ) == Map(INTEGER)
        assert read({"type": "object"}) == Map(ANY)
        assert read({"properties": {"a": {"type": "string"}}}) == Map(ANY)

    def test_enums(self) -> None:
        assert read({"enum": ["a", "b"]}) == Enum(("a", "b"))
        assert read({"enum": ["a", None]}) == Enum(("a", None))

    def test_enum_with_non_literal_values_degrades_to_any(self) -> None:
        """Regression: Literal[1.5] is not valid typing (PEP 586)."""
        assert read({"enum": [1.5, "a"]}) == ANY
        assert read({"enum": [[1]]}) == ANY
        assert read({"enum": []}) == ANY

    def test_formats_and_booleans(self) -> None:
        assert read({"type": "string", "format": "binary"}) == BINARY
        assert read(True) == ANY
        assert read({}) == ANY
        assert read(None) == ANY
        assert read(False) == NEVER

    def test_junk_degrades_to_any(self) -> None:
        assert read({"type": "wibble"}) == ANY
        assert read("not a schema") == ANY
        assert read({"type": 42}) == ANY


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def edge() -> ir.Api:
    return parse(load(FIXTURES / "edgecases.json"))


def operation(api: ir.Api, method: ir.Method, path: str) -> ir.Operation:
    return next(op for op in api.operations if op.method is method and op.path == path)


class TestParseModels:
    def test_metadata(self, edge: ir.Api) -> None:
        assert edge.title == "Edge Cases"
        assert edge.version == "2.3.4"
        assert '"quotes"' in edge.description

    def test_wire_keys_kept_verbatim(self, edge: ir.Api) -> None:
        user = edge.model("User")
        assert [f.name for f in user.fields] == ["id", "type", "user-name", "class"]
        assert user.fields[0] == ir.Field("id", INTEGER, required=True)
        assert user.fields[1].type == Enum(("admin", "guest"))
        assert user.fields[2].doc == "hyphenated wire key"
        assert user.fields[2].required is False

    def test_recursive_model(self, edge: ir.Api) -> None:
        tree = edge.model("Tree")
        assert tree.fields[0].type == ir.union(STRING, NULL)
        assert tree.fields[1].type == Array(Ref("Tree"))
        assert edge.dependencies()["Tree"] == {"Tree"}

    def test_all_of_flattened(self, edge: ir.Api) -> None:
        admin = edge.model("Admin")
        assert {f.name: f.required for f in admin.fields} == {
            "message": False,
            "level": True,
        }
        assert admin.doc == "allOf inheritance"

    def test_components_null_is_tolerated(self) -> None:
        """Regression: a chained .get() crashed on "components": null."""
        api = parse({"openapi": "3.0.0", "info": {}, "components": None, "paths": None})
        assert api.models == ()
        assert api.operations == ()


class TestParseOperations:
    def test_path_item_param_override_and_header_naming(self, edge: ir.Api) -> None:
        op = operation(edge, ir.Method.GET, "/users/{user_id}")
        by_name = {p.name: p for p in op.params}
        assert set(by_name) == {"user_id", "verbose", "x_trace_id"}
        # operation-level (integer) overrides path-level (string)
        assert by_name["user_id"].type == INTEGER
        assert by_name["user_id"].required is True
        assert by_name["verbose"].default == ir.Default(False)
        assert by_name["x_trace_id"] == ir.Param(
            "x_trace_id", "X-Trace-Id", ir.Location.HEADER, STRING, required=False
        )
        assert op.doc == "Get a user\n\nPath-level description"

    def test_responses_kept_per_status(self, edge: ir.Api) -> None:
        op = operation(edge, ir.Method.GET, "/users/{user_id}")
        assert op.responses == (
            ir.Response(200, Ref("User")),
            ir.Response(404, Ref("Error")),
        )
        assert op.success == Ref("User")
        assert op.error == Ref("Error")

    def test_body_slots(self, edge: ir.Api) -> None:
        delete = operation(edge, ir.Method.DELETE, "/users/{user_id}")
        assert delete.body == ir.Body(
            ir.Slot.JSON, Map(STRING), required=True, doc="Request body."
        )
        assert delete.responses == (ir.Response(204, NULL),)
        assert delete.success == NULL

        upload = operation(edge, ir.Method.POST, "/upload")
        assert upload.body is not None
        assert upload.body.slot is ir.Slot.CONTENT
        assert upload.body.type == BINARY

    def test_collisions_resolved(self, edge: ir.Api) -> None:
        op = operation(edge, ir.Method.GET, "/search")
        assert [(p.name, p.api_name) for p in op.params] == [
            ("json_query", "json"),
            ("pet_id", "petId"),
            ("pet_id_query", "pet_id"),
        ]

    def test_ref_param_and_ref_response(self, edge: ir.Api) -> None:
        op = operation(edge, ir.Method.GET, "/ref-param")
        assert op.params == (
            ir.Param(
                "page",
                "page",
                ir.Location.QUERY,
                INTEGER,
                required=False,
                default=ir.Default(1),
            ),
        )
        assert op.success == Ref("User")

    def test_path_params_are_always_required(self) -> None:
        api = parse(
            {
                "openapi": "3.0.0",
                "info": {},
                "paths": {
                    "/x/{id}": {
                        "get": {
                            "parameters": [{"name": "id", "in": "path", "schema": {}}],
                            "responses": {},
                        }
                    }
                },
            }
        )
        assert api.operations[0].params[0].required is True
        assert api.operations[0].success == ANY
