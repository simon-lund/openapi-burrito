"""Tests for the frontend: naming, $ref resolution, type reading, parse()."""

from pathlib import Path
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
from openapi_burrito.spec import load, naming, parse
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
