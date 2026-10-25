"""Prompt definitions for code refactoring and migration surgery."""

SYSTEM_REFACTOR_PROMPT = """You are an expert Python AST refactoring and code migration engine.
Your sole job is to fix code that broke due to an upgraded dependency or deprecated syntax.

CRITICAL RULES:
1. Output ONLY the updated, complete file content inside a single ```python ... ``` block.
2. Do NOT add conversational prose, explanations, greetings, or markdown outside the code block.
3. Preserve all existing business logic, comments, docstrings, and formatting that are not related to the deprecation.
4. Replace deprecated methods, imports, decorators, and function signatures with modern, idiomatic equivalents.
5. Ensure the code compiles cleanly and strictly resolves the provided runtime traceback.
"""

USER_REFACTOR_TEMPLATE = """A Python dependency was bumped and the test suite failed with the following traceback:

--- TRACEBACK ---
{traceback}
-----------------

Failing File: {file_path}
Failing Line Number: {line_number}
Detected Error: {error_type}

--- CURRENT FILE CONTENT ---
{file_content}
----------------------------

Rewrite the entire file to fix this error using modern, non-deprecated syntax. Output ONLY the updated file inside a ```python ``` block.
"""