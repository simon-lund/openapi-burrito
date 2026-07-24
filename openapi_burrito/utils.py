import re


def to_snake_case(name: str) -> str:
    """
    Converts camelCase or PascalCase to snake_case.
    Handles acronyms gracefully (e.g., HTTPResponse -> http_response).
    """
    # Insert underscore between lower+upper (e.g., camelCase -> camel_Case)
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Insert underscore between lower/digit+upper
    # (e.g., camel_Case -> camel_Case, HTTP -> HTTP)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    # Collapse runs from pre-separated input (e.g. X_Trace_Id -> x_trace_id,
    # not x__trace__id)
    return re.sub("_+", "_", s2)


def normalize_path(path: str, renames: dict[str, str] | None = None) -> str:
    """
    Converts path parameter names to snake_case.
    e.g., /pet/{petId} -> /pet/{pet_id}

    :param renames: Optional mapping of original parameter names to their final
        Python names (used when collision handling renamed an argument), taking
        precedence over plain snake_casing.
    """
    renames = renames or {}

    def replace(m: re.Match[str]) -> str:
        name = m.group(1)
        return "{" + renames.get(name, to_snake_case(name)) + "}"

    return re.sub(r"\{([^}]+)\}", replace, path)
