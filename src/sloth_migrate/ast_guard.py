"""AST validation and syntax verification guardrails for SlothMigrate."""

import ast
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Outcome of static syntax and AST compilation check."""
    is_valid: bool
    error_message: str | None = None
    line_number: int | None = None


def validate_python_code(code: str, filename: str = "<patch>") -> ValidationResult:
    """Parses code into a concrete Python AST to ensure zero syntax errors before saving."""
    if not code or not code.strip():
        return ValidationResult(
            is_valid=False,
            error_message="Generated code is empty",
        )

    try:
        ast.parse(code, filename=filename)
        return ValidationResult(is_valid=True)
    except SyntaxError as err:
        return ValidationResult(
            is_valid=False,
            error_message=f"{err.msg} (line {err.lineno}, col {err.offset})",
            line_number=err.lineno,
        )
    except Exception as err:
        return ValidationResult(
            is_valid=False,
            error_message=f"AST parse failure: {err}",
        )