"""Tests for security-critical sanitization functions."""

import pytest

from openapi_burrito.parser.sanitize import safe_bool, safe_status, sanitize


class TestSanitizeIdentifier:
    """Tests for identifier sanitization (mode='id')."""

    # Basic functionality
    def test_simple_name(self) -> None:
        assert sanitize("User", mode="id") == "User"

    def test_with_hyphens(self) -> None:
        assert sanitize("user-profile", mode="id") == "user_profile"

    def test_with_spaces(self) -> None:
        assert sanitize("user profile", mode="id") == "user_profile"

    def test_starts_with_digit(self) -> None:
        assert sanitize("123abc", mode="id") == "_123abc"

    # Python keywords
    def test_keyword_class(self) -> None:
        assert sanitize("class", mode="id") == "class_"

    def test_keyword_return(self) -> None:
        assert sanitize("return", mode="id") == "return_"

    def test_keyword_if(self) -> None:
        assert sanitize("if", mode="id") == "if_"

    # Builtins protection
    def test_builtin_list(self) -> None:
        assert sanitize("list", mode="id") == "list_"

    def test_builtin_dict(self) -> None:
        assert sanitize("dict", mode="id") == "dict_"

    def test_builtin_type(self) -> None:
        assert sanitize("type", mode="id") == "type_"

    def test_builtin_str(self) -> None:
        assert sanitize("str", mode="id") == "str_"

    def test_id_allowed(self) -> None:
        # 'id' is commonly used in APIs, we allow it
        assert sanitize("id", mode="id") == "id"

    # Invalid input handling (should raise ValueError)
    def test_empty_after_sanitize_raises(self) -> None:
        with pytest.raises(ValueError, match="empty or invalid"):
            sanitize("!!!", mode="id")

    def test_all_special_chars_raises(self) -> None:
        with pytest.raises(ValueError, match="empty or invalid"):
            sanitize("@#$%", mode="id")

    def test_only_hyphens_raises(self) -> None:
        with pytest.raises(ValueError, match="empty or invalid"):
            sanitize("---", mode="id")

    # Injection attempts
    def test_injection_newline(self) -> None:
        result = sanitize("Foo:\n    pass\nimport os", mode="id")
        assert "\n" not in result
        assert result.isidentifier()

    def test_injection_quotes(self) -> None:
        result = sanitize('foo"bar', mode="id")
        assert '"' not in result
        assert result.isidentifier()

    def test_injection_code_block(self) -> None:
        result = sanitize(
            "User:\n    pass\nimport os; os.system('rm -rf /')  # ", mode="id"
        )
        assert "\n" not in result
        # The word 'import' might appear as text,
        # but no actual newlines or code structure
        assert result.isidentifier()
        assert result == "User_pass_import_os_os_system_rm_rf"


class TestSanitizeString:
    """Tests for string literal escaping (mode='str')."""

    def test_double_quotes(self) -> None:
        assert sanitize('foo"bar', mode="str") == 'foo\\"bar'

    def test_single_quotes(self) -> None:
        assert sanitize("foo'bar", mode="str") == "foo\\'bar"

    def test_newlines(self) -> None:
        assert sanitize("foo\nbar", mode="str") == "foo\\nbar"

    def test_carriage_return(self) -> None:
        assert sanitize("foo\rbar", mode="str") == "foo\\rbar"

    def test_tab(self) -> None:
        assert sanitize("foo\tbar", mode="str") == "foo\\tbar"

    def test_backslash(self) -> None:
        assert sanitize("foo\\bar", mode="str") == "foo\\\\bar"

    def test_injection_attempt(self) -> None:
        # CVE-2020-15142 style attack
        payload = '" + __import__("os").system("id") + "\''
        result = sanitize(payload, mode="str")
        # Quotes should be escaped with backslash
        assert '\\"' in result  # Escaped quotes present
        # The escape sequence transforms " into \"
        assert result == '\\" + __import__(\\"os\\").system(\\"id\\") + \\"\\\''

    def test_path_injection(self) -> None:
        payload = '/users"]\n) -> None: pass\nimport os  # '
        result = sanitize(payload, mode="str")
        assert "\n" not in result
        assert '"' not in result.replace('\\"', "")


class TestSanitizeDocstring:
    """Tests for docstring escaping (mode='doc')."""

    def test_triple_double_quotes(self) -> None:
        assert sanitize('foo"""bar', mode="doc") == r"foo\"\"\"bar"

    def test_triple_single_quotes(self) -> None:
        assert sanitize("foo'''bar", mode="doc") == r"foo\'\'\'bar"

    def test_normal_text_unchanged(self) -> None:
        text = "This is a normal description."
        assert sanitize(text, mode="doc") == text

    def test_docstring_closure_attempt(self) -> None:
        payload = 'Description"""\nimport os\n"""'
        result = sanitize(payload, mode="doc")
        # No un-escaped triple quotes may survive
        assert '"""' not in result
        # Embedding in a docstring must remain a single valid string
        compile(f'"""{result}"""', "<test>", "eval")

    def test_trailing_backslash_escaped(self) -> None:
        # A trailing backslash must not swallow the closing quotes
        result = sanitize("ends with \\", mode="doc")
        assert result == "ends with \\\\"
        compile(f'"""{result}"""', "<test>", "eval")


class TestSafeBool:
    def test_missing_key_returns_default(self) -> None:
        assert safe_bool({}, "required") is False
        assert safe_bool({}, "required", default=True) is True

    def test_truthy_values(self) -> None:
        assert safe_bool({"req": True}, "req") is True
        assert safe_bool({"req": "yes"}, "req") is True
        assert safe_bool({"req": 1}, "req") is True

    def test_falsy_values(self) -> None:
        assert safe_bool({"req": False}, "req") is False
        assert safe_bool({"req": 0}, "req") is False
        assert safe_bool({"req": ""}, "req") is False
        assert safe_bool({"req": None}, "req") is False


class TestSafeStatus:
    def test_valid_integer_string(self) -> None:
        assert safe_status("200") == 200
        assert safe_status("404") == 404

    def test_valid_integer(self) -> None:
        # Should handle int input even if type hint says str (defensive)
        assert safe_status(200) == 200  # type: ignore

    def test_invalid_string(self) -> None:
        assert safe_status("default") is None
        assert safe_status("foo") is None

    def test_empty_string(self) -> None:
        assert safe_status("") is None
