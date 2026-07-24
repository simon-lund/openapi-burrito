"""
Property-based tests (Hypothesis).

Example-based tests check hand-picked inputs; property-based tests state a
rule that must hold for EVERY input, and Hypothesis generates hundreds of
adversarial inputs per run trying to break it (then shrinks any failure to
the smallest counterexample).

This matters most for sanitize.py: its security claim is universally
quantified — "no spec string, whatever it contains, can break out of the
generated code" — which a finite list of examples can suggest but never
state. These properties state it.
"""

import ast
import keyword

import pytest
from hypothesis import given
from hypothesis import strategies as st

from openapi_burrito.parser.resolver import RefResolver
from openapi_burrito.parser.sanitize import sanitize
from openapi_burrito.parser.types import TypeTranslator
from openapi_burrito.utils import to_snake_case


class TestSanitizeProperties:
    @given(st.text())
    def test_identifier_mode_always_yields_safe_identifier(self, s: str) -> None:
        """For ANY string: a valid, non-keyword identifier — or a loud error."""
        try:
            result = sanitize(s, mode="id")
        except ValueError:
            return  # explicit rejection is fine; silent breakage is not
        assert result.isidentifier()
        assert not keyword.iskeyword(result)

    @given(st.text())
    def test_identifier_mode_is_idempotent(self, s: str) -> None:
        """Sanitizing twice must not change the result (stability)."""
        try:
            once = sanitize(s, mode="id")
        except ValueError:
            return
        assert sanitize(once, mode="id") == once

    @given(st.text())
    def test_string_mode_roundtrips_through_a_literal(self, s: str) -> None:
        """
        The exact security claim for mode="str": embedding the escaped value
        in a double-quoted literal yields valid Python that evaluates back to
        the original string — no breakout, no corruption.
        """
        escaped = sanitize(s, mode="str")
        assert ast.literal_eval(f'"{escaped}"') == s

    @given(st.text())
    def test_doc_mode_never_breaks_the_docstring(self, s: str) -> None:
        """
        mode="doc" output is embedded between triple quotes with surrounding
        newlines (as the templates do). That must always compile — a failure
        here would mean a spec description can terminate the docstring and
        smuggle in executable code.
        """
        escaped = sanitize(s, mode="doc")
        compile(f'"""\n{escaped}\n"""', "<probe>", "eval")

    @given(st.text())
    def test_doc_mode_roundtrips(self, s: str) -> None:
        """Docstring content survives verbatim for ANY input string."""
        escaped = sanitize(s, mode="doc")
        value = ast.literal_eval(f'"""\n{escaped}\n"""')
        assert value == f"\n{s}\n"


class TestSnakeCaseProperties:
    @given(st.text(alphabet=st.characters(codec="ascii", categories=("L", "N", "P"))))
    def test_idempotent(self, s: str) -> None:
        """snake_casing an already snake_cased name must be a no-op."""
        once = to_snake_case(s)
        assert to_snake_case(once) == once


# JSON-representable values, as they may appear in enums/defaults
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda children: st.lists(children, max_size=3)
    | st.dictionaries(st.text(max_size=10), children, max_size=3),
    max_leaves=5,
)

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


class TestTypeTranslatorProperties:
    @given(schemas)
    def test_output_is_always_a_valid_type_expression(self, schema: object) -> None:
        """
        Whatever schema shape comes in — junk types, nested composition,
        adversarial enum values — the translator must emit a string that
        parses as a Python expression (degrading to "Any" is fine, emitting
        syntax errors into generated code is not).
        """
        translator = TypeTranslator(RefResolver({}))
        try:
            rendered = translator(schema)
        except (ValueError, RecursionError):
            pytest.skip("translator rejected the schema loudly — acceptable")
        compile(rendered, "<probe>", "eval")
