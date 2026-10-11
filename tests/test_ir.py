"""Tests for the IR: value semantics, union normalization, reference queries."""

import pytest

from openapi_burrito import ir
from openapi_burrito.ir import (
    ANY,
    BOOLEAN,
    INTEGER,
    NEVER,
    NULL,
    STRING,
    Api,
    Array,
    Enum,
    Field,
    Map,
    Method,
    Model,
    Operation,
    Ref,
    Response,
    Union,
    refs,
    union,
)


class TestValueSemantics:
    def test_equal_by_structure_and_hashable(self) -> None:
        a = Array(Union((Ref("Pet"), NULL)))
        b = Array(Union((Ref("Pet"), NULL)))
        assert a == b
        assert a is not b
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            Ref("Pet").name = "Dog"  # type: ignore[misc]


class TestUnion:
    def test_two_members(self) -> None:
        assert union(STRING, INTEGER) == Union((INTEGER, STRING))

    def test_order_independent(self) -> None:
        assert union(STRING, INTEGER) == union(INTEGER, STRING)

    def test_single_member_collapses(self) -> None:
        assert union(STRING) == STRING
        assert union(STRING, STRING) == STRING

    def test_empty_is_any(self) -> None:
        assert union() == ANY

    def test_flattens_nested(self) -> None:
        assert union(Union((STRING, INTEGER)), BOOLEAN) == union(
            STRING, INTEGER, BOOLEAN
        )

    def test_any_absorbs(self) -> None:
        assert union(STRING, ANY) == ANY
        assert union(Union((STRING, ANY)), INTEGER) == ANY

    def test_never_is_dropped(self) -> None:
        assert union(STRING, NEVER) == STRING
        assert union(NEVER) == ANY  # nothing left: permissive, not bottom

    def test_null_is_an_ordinary_member(self) -> None:
        result = union(Ref("Pet"), NULL)
        assert isinstance(result, Union)
        assert set(result.members) == {Ref("Pet"), NULL}
        assert union(Ref("Pet"), NULL, NULL) == result

    def test_enums_merge(self) -> None:
        assert union(Enum(("a",)), Enum(("b", "a"))) == Enum(("a", "b"))
        assert union(Enum(("a",)), STRING) == Union((Enum(("a",)), STRING))


class TestEnum:
    def test_accepts_literal_able_values(self) -> None:
        Enum(("a", 1, True, None))

    @pytest.mark.parametrize("bad", [1.5, [1], {"a": 1}])
    def test_rejects_values_that_cannot_be_literals(self, bad: object) -> None:
        with pytest.raises(TypeError, match="cannot be a Literal"):
            Enum(("a", bad))  # type: ignore[arg-type]


class TestRefs:
    def test_collects_at_any_depth(self) -> None:
        expr = Array(Map(Union((Ref("A"), Array(Ref("B")), STRING))))
        assert refs(expr) == {"A", "B"}
        assert refs(STRING) == frozenset()

    def test_model_refs(self) -> None:
        tree = Model(
            "Tree",
            (
                Field("name", STRING, required=False),
                Field("children", Array(Ref("Tree")), required=False),
                Field("owner", Ref("User"), required=True),
            ),
        )
        assert tree.refs() == {"Tree", "User"}

    def test_api_dependencies(self) -> None:
        api = Api(
            title="t",
            version="1",
            description="",
            models=(
                Model("User", (Field("pets", Array(Ref("Pet")), required=False),)),
                Model("Pet", (Field("owner", Ref("User"), required=False),)),
                Model("Tag", (Field("name", STRING, required=True),)),
            ),
            operations=(),
        )
        assert api.dependencies() == {
            "User": {"Pet"},
            "Pet": {"User"},
            "Tag": frozenset(),
        }
        assert api.model("Tag").fields[0].name == "name"
        with pytest.raises(KeyError):
            api.model("Nope")


class TestOperation:
    def test_success_and_error_are_derived_unions(self) -> None:
        op = Operation(
            Method.GET,
            "/pet/{pet_id}",
            responses=(
                Response(200, Ref("Pet")),
                Response(201, Ref("Pet")),
                Response(204, NULL),
                Response(404, Ref("Error")),
                Response(500, Ref("Error")),
            ),
        )
        assert op.success == union(Ref("Pet"), NULL)
        assert op.error == Ref("Error")

    def test_no_responses_means_any(self) -> None:
        op = Operation(Method.DELETE, "/x")
        assert op.success == ANY
        assert op.error == ANY

    def test_refs_span_params_body_and_responses(self) -> None:
        op = Operation(
            Method.POST,
            "/pet",
            params=(
                ir.Param("tag", "tag", ir.Location.QUERY, Ref("Tag"), required=False),
            ),
            body=ir.Body(ir.Slot.JSON, Ref("NewPet"), required=True),
            responses=(Response(200, Ref("Pet")),),
        )
        assert op.refs() == {"Tag", "NewPet", "Pet"}
