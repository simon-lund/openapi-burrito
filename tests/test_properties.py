"""
Property-based tests (Hypothesis).

Example-based tests check hand-picked inputs; property-based tests state a
rule that must hold for EVERY input, and Hypothesis generates hundreds of
adversarial inputs per run trying to break it (then shrinks any failure to
the smallest counterexample).

The security claim of the emitter is universally quantified — "no spec
string, whatever it contains, can break out of the generated code" — which a
finite list of examples can suggest but never state. These properties state it.
"""

import ast
import keyword
import math

from hypothesis import given
from hypothesis import strategies as st

from openapi_burrito import ir
from openapi_burrito.emit import docstring, literal, render_type
from openapi_burrito.spec import naming
from openapi_burrito.spec.resolver import RefResolver
from openapi_burrito.spec.types import type_expr

# JSON-representable values, as they may appear in enums/defaults
json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=10), children, max_size=3),
    max_leaves=5,
)


class TestNamingProperties:
    @given(st.text())
    def test_identifier_always_yields_safe_identifier(self, s: str) -> None:
        """For ANY string: a valid, non-keyword identifier — or a loud error."""
        try:
            result = naming.identifier(s)
        except ValueError:
            return  # explicit rejection is fine; silent breakage is not
        assert result.isidentifier()
        assert not keyword.iskeyword(result)

    @given(st.text())
    def test_identifier_is_idempotent(self, s: str) -> None:
        try:
            once = naming.identifier(s)
        except ValueError:
            return
        assert naming.identifier(once) == once

    @given(st.text(alphabet=st.characters(codec="ascii", categories=("L", "N", "P"))))
    def test_snake_case_is_idempotent(self, s: str) -> None:
        once = naming.snake_case(s)
        assert naming.snake_case(once) == once


class TestSpellingProperties:
    @given(json_values)
    def test_literal_roundtrips(self, value: object) -> None:
        """
        The exact security claim for literals: the rendered text is a Python
        literal that evaluates back to the original value — no breakout, no
        corruption, for ANY JSON value.
        """
        assert ast.literal_eval(literal(value)) == value

    @given(st.sampled_from([float("inf"), float("-inf")]))
    def test_non_finite_floats_render_as_expressions(self, value: float) -> None:
        """YAML can carry .inf; Python has no literal for it, only float('inf')."""
        assert eval(literal(value)) == value
        assert math.isnan(eval(literal(float("nan"))))

    @given(st.text())
    def test_docstring_never_breaks_out(self, s: str) -> None:
        """
        Docstring text is embedded between triple quotes with surrounding
        newlines (as the templates do). That must always compile — a failure
        here would mean a spec description can terminate the docstring and
        smuggle in executable code — and must evaluate back to the input.
        """
        escaped = docstring(s)
        value = ast.literal_eval(f'"""\n{escaped}\n"""')
        assert value == f"\n{s}\n"


# Schema-shaped dicts: valid keys with adversarial values, plus junk keys
schemas = st.recursive(
    st.dictionaries(
        st.sampled_from(
            ["type", "format", "enum", "items", "properties", "nullable", "default"]
        ),
        json_values,
        max_size=4,
    ),
    lambda children: st.fixed_dictionaries(
        {},
        optional={
            "type": st.sampled_from(
                ["object", "array", "string", "integer", "number", "boolean", "null"]
            )
            | st.text(max_size=8),
            "items": children,
            "properties": st.dictionaries(st.text(max_size=8), children, max_size=3),
            "oneOf": st.lists(children, max_size=3),
            "anyOf": st.lists(children, max_size=3),
            "allOf": st.lists(children, max_size=3),
            "enum": st.lists(json_values, max_size=3),
            "nullable": st.booleans(),
        },
    ),
    max_leaves=8,
)


class TestTypeProperties:
    @given(schemas)
    def test_any_schema_yields_a_valid_type_expression(self, schema: object) -> None:
        """
        Whatever schema shape comes in — junk types, nested composition,
        adversarial enum values — reading it must not raise, and the rendered
        type must parse as a Python expression (degrading to Any is fine,
        emitting syntax errors into generated code is not).
        """
        expr = type_expr(schema, RefResolver({}))
        compile(render_type(expr), "<probe>", "eval")

    @given(
        st.lists(st.sampled_from([ir.STRING, ir.INTEGER, ir.NULL, ir.ANY, ir.NEVER]))
    )
    def test_union_is_idempotent_and_order_independent(
        self, members: list[ir.TypeExpr]
    ) -> None:
        once = ir.union(*members)
        assert ir.union(once) == once
        assert ir.union(*reversed(members)) == once
