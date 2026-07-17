"""Unit tests for the $ref resolver and the type translator."""

from typing import Any

from openapi_burrito.parser.resolver import RefResolver
from openapi_burrito.parser.types import TypeTranslator


def make_translator(schemas: dict[str, Any] | None = None) -> TypeTranslator:
    spec = {"components": {"schemas": schemas or {}}}
    return TypeTranslator(RefResolver(spec))


class TestRefResolver:
    def test_schema_name_for_named_schema(self) -> None:
        resolver = RefResolver({})
        assert resolver.schema_name("#/components/schemas/Pet") == "Pet"

    def test_schema_name_sanitized(self) -> None:
        resolver = RefResolver({})
        assert resolver.schema_name("#/components/schemas/my-pet") == "my_pet"

    def test_schema_name_rejects_nested_pointer(self) -> None:
        resolver = RefResolver({})
        assert resolver.schema_name("#/components/schemas/Pet/properties/id") is None

    def test_schema_name_rejects_other_locations(self) -> None:
        resolver = RefResolver({})
        assert resolver.schema_name("#/components/parameters/Page") is None
        assert resolver.schema_name(None) is None

    def test_deref_follows_chain(self) -> None:
        spec = {
            "components": {
                "schemas": {
                    "A": {"$ref": "#/components/schemas/B"},
                    "B": {"type": "string"},
                }
            }
        }
        resolver = RefResolver(spec)
        assert resolver.deref({"$ref": "#/components/schemas/A"}) == {"type": "string"}

    def test_deref_passthrough_without_ref(self) -> None:
        resolver = RefResolver({})
        assert resolver.deref({"type": "integer"}) == {"type": "integer"}
        assert resolver.deref(None) is None

    def test_deref_circular_chain_returns_empty(self) -> None:
        spec = {
            "components": {
                "schemas": {
                    "A": {"$ref": "#/components/schemas/B"},
                    "B": {"$ref": "#/components/schemas/A"},
                }
            }
        }
        resolver = RefResolver(spec)
        assert resolver.deref({"$ref": "#/components/schemas/A"}) == {}

    def test_deref_broken_ref_returns_empty(self) -> None:
        resolver = RefResolver({})
        assert resolver.deref({"$ref": "#/components/schemas/Nope"}) == {}

    def test_deref_pointer_escaping(self) -> None:
        spec = {"components": {"schemas": {"a/b": {"type": "integer"}}}}
        resolver = RefResolver(spec)
        assert resolver.deref({"$ref": "#/components/schemas/a~1b"}) == {
            "type": "integer"
        }


class TestTypeTranslator:
    def test_ref_becomes_model_name(self) -> None:
        translator = make_translator({"Pet": {"type": "object"}})
        assert translator({"$ref": "#/components/schemas/Pet"}) == "Pet"

    def test_recursive_ref_terminates(self) -> None:
        translator = make_translator(
            {
                "Node": {
                    "type": "object",
                    "properties": {
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Node"},
                        }
                    },
                }
            }
        )
        schema = {"type": "array", "items": {"$ref": "#/components/schemas/Node"}}
        assert translator(schema) == "list[Node]"

    def test_nullable_ref_sibling(self) -> None:
        translator = make_translator({"Pet": {"type": "object"}})
        assert translator({"$ref": "#/components/schemas/Pet", "nullable": True}) == (
            "Pet | None"
        )

    def test_openapi31_type_array_keeps_none(self) -> None:
        translator = make_translator()
        assert translator({"type": ["string", "null"]}) == "str | None"

    def test_oneof_with_null_type_keeps_none(self) -> None:
        translator = make_translator()
        schema = {"oneOf": [{"type": "string"}, {"type": "null"}]}
        assert translator(schema) == "str | None"

    def test_anyof_is_union(self) -> None:
        translator = make_translator()
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        assert translator(schema) == "int | str"

    def test_single_item_allof_unwrapped(self) -> None:
        translator = make_translator({"Pet": {"type": "object"}})
        schema = {"allOf": [{"$ref": "#/components/schemas/Pet"}]}
        assert translator(schema) == "Pet"

    def test_enum_literals(self) -> None:
        translator = make_translator()
        assert translator({"enum": ["a", "b"]}) == 'Literal["a", "b"]'

    def test_binary_string_is_bytes(self) -> None:
        translator = make_translator()
        assert translator({"type": "string", "format": "binary"}) == "bytes"

    def test_boolean_schemas(self) -> None:
        translator = make_translator()
        assert translator(True) == "Any"
        assert translator({}) == "Any"
        assert translator(False) == "Never"

    def test_unknown_type_defaults_to_any(self) -> None:
        translator = make_translator()
        assert translator({"type": "wibble"}) == "Any"
