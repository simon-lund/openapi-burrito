"""Unit tests for utility functions."""

from openapi_burrito.utils import normalize_path, to_snake_case


class TestToSnakeCase:
    def test_simple_lowercase(self) -> None:
        assert to_snake_case("foo") == "foo"

    def test_camel_case(self) -> None:
        assert to_snake_case("camelCase") == "camel_case"

    def test_pascal_case(self) -> None:
        assert to_snake_case("PascalCase") == "pascal_case"

    def test_with_acronyms(self) -> None:
        assert to_snake_case("HTTPResponse") == "http_response"
        assert to_snake_case("UserID") == "user_id"

    def test_mixed_numbers(self) -> None:
        assert to_snake_case("User123Name") == "user123_name"

    def test_pre_separated_input_collapses(self) -> None:
        # e.g. header names sanitized before snake_casing: X-Trace-Id -> X_Trace_Id
        assert to_snake_case("X_Trace_Id") == "x_trace_id"


class TestNormalizePath:
    def test_no_params(self) -> None:
        assert normalize_path("/users") == "/users"

    def test_single_param(self) -> None:
        assert normalize_path("/users/{userId}") == "/users/{user_id}"

    def test_multiple_params(self) -> None:
        assert (
            normalize_path("/users/{userId}/posts/{postID}")
            == "/users/{user_id}/posts/{post_id}"
        )

    def test_preserve_non_param_braces(self) -> None:
        # Only path params are in braces; ensure simple cases stay intact
        assert normalize_path("/{id}") == "/{id}"

    def test_renames_take_precedence(self) -> None:
        # Collision handling renamed the arg; the placeholder must follow
        assert normalize_path("/x/{json}", {"json": "json_path"}) == "/x/{json_path}"

    def test_renames_fix_non_identifier_params(self) -> None:
        assert (
            normalize_path("/x/{user-name}", {"user-name": "user_name"})
            == "/x/{user_name}"
        )
