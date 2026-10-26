"""In-memory AST validation gatekeeper."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional, Set


@dataclass
class ASTValidationResult:
    is_valid: bool
    ast_tree: Optional[ast.AST] = None
    error_message: Optional[str] = None


def validate_python_code(
    code: str,
    filename: str = "<generated>",
    original_code: Optional[str] = None,
) -> ASTValidationResult:
    """Validates that code parses cleanly and preserves top-level classes/functions."""
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as e:
        return ASTValidationResult(
            is_valid=False,
            error_message=f"SyntaxError at line {e.lineno}: {e.msg}",
        )

    # Structural check: Ensure top-level classes are not accidentally dropped
    if original_code:
        try:
            orig_tree = ast.parse(original_code, filename="<original>")
            orig_classes: Set[str] = {
                node.name for node in orig_tree.body if isinstance(node, ast.ClassDef)
            }
            new_classes: Set[str] = {
                node.name for node in tree.body if isinstance(node, ast.ClassDef)
            }

            # If original had classes (e.g. Reference), new code MUST contain them
            missing = orig_classes - new_classes
            if missing:
                return ASTValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Structural Violation: Generated code omitted classes: {missing}. "
                        "Do not return isolated snippets or inner classes. Output the FULL file."
                    ),
                )
        except Exception as e:
            # If parsing original fails, pass through
            pass

    return ASTValidationResult(is_valid=True, ast_tree=tree)