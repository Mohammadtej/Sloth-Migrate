"""Atomic Temporal activities for SlothMigrate."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from temporalio import activity

from sloth_migrate.ast_guard import validate_python_code
from sloth_migrate.ecosystems.python_ecosystem import PythonEcosystem
from sloth_migrate.llm.client import gemma_client
from sloth_migrate.llm.prompts import SYSTEM_REFACTOR_PROMPT, USER_REFACTOR_TEMPLATE


class BumpParams(BaseModel):
    repo_path: str
    package: str
    target_version: str


class FailureInfo(BaseModel):
    file_path: str
    line_number: Optional[int] = None
    error_type: str
    raw_traceback: str


class TestRunParams(BaseModel):
    repo_path: str


class TestRunResult(BaseModel):
    exit_code: int
    output: str
    failures: list[FailureInfo] = Field(default_factory=list)
    failing_files: list[str] = Field(default_factory=list)


class PatchParams(BaseModel):
    repo_path: str
    target_file: str
    line_number: Optional[int] = None
    error_type: str = "Deprecation / Breaking Change"
    raw_traceback: str


class PatchResult(BaseModel):
    success: bool
    modified_file: str
    diff: str = ""
    error_message: str | None = None


@activity.defn
async def bump_and_install_activity(params: BumpParams) -> bool:
    repo_dir = Path(params.repo_path).resolve()
    ecosystem = PythonEcosystem()
    ecosystem.bump_dependency(repo_dir, params.package, params.target_version)
    installed, _ = ecosystem.install_dependency(params.package, params.target_version)
    return installed


@activity.defn
async def run_tests_activity(params: TestRunParams) -> TestRunResult:
    repo_dir = Path(params.repo_path).resolve()
    ecosystem = PythonEcosystem()
    exit_code, output = ecosystem.run_tests(repo_dir)
    failures = ecosystem.parse_traceback(output, repo_dir)

    failure_items = [
        FailureInfo(
            file_path=str(f.file_path),
            line_number=f.line_number,
            error_type=f.error_type,
            raw_traceback=f.raw_traceback,
        )
        for f in failures
    ]

    return TestRunResult(
        exit_code=exit_code,
        output=output,
        failures=failure_items,
        failing_files=[str(f.file_path) for f in failures],
    )


@activity.defn
async def generate_and_apply_patch_activity(params: PatchParams) -> PatchResult:
    repo_dir = Path(params.repo_path).resolve()
    target_file = Path(params.target_file).resolve()

    if not target_file.exists():
        print(f"[Worker Error] Target file not found: {target_file}")
        return PatchResult(
            success=False,
            modified_file=str(target_file),
            diff="",
            error_message=f"File not found: {target_file}",
        )

    original_code = target_file.read_text(encoding="utf-8")

    # Safe relative path display for prompt
    try:
        display_path = str(target_file.relative_to(repo_dir))
    except ValueError:
        display_path = target_file.name

    user_prompt = USER_REFACTOR_TEMPLATE.format(
        traceback=params.raw_traceback,
        file_path=display_path,
        line_number=params.line_number or "N/A",
        error_type=params.error_type,
        file_content=original_code,
    )

    print(f"\n[Worker] Calling Gemma to refactor: {target_file.name} (Line: {params.line_number}, Error: {params.error_type[:40]})...")
    try:
        repaired_code = await gemma_client.generate_fix(
            system_prompt=SYSTEM_REFACTOR_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception as e:
        print(f"[Worker Error] LLM generation failed: {e}")
        return PatchResult(
            success=False,
            modified_file=str(target_file),
            diff="",
            error_message=f"LLM generation failed: {e}",
        )

    if repaired_code.strip() == original_code.strip():
        print("[Worker Warning] Gemma returned identical code without fixes.")
        return PatchResult(
            success=False,
            modified_file=str(target_file),
            diff="",
            error_message="Gemma returned identical code without fixes.",
        )

    # In-memory AST validation gatekeeper
    validation = validate_python_code(
        repaired_code,
        filename=target_file.name,
        original_code=original_code,
    )
    if not validation.is_valid:
        print(f"[Worker Warning] AST validation failed: {validation.error_message}")
        return PatchResult(
            success=False,
            modified_file=str(target_file),
            diff="",
            error_message=f"AST Validation Failed: {validation.error_message}",
        )

    diff_lines = list(
        difflib.unified_diff(
            original_code.splitlines(),
            repaired_code.splitlines(),
            fromfile=f"a/{target_file.name} (legacy)",
            tofile=f"b/{target_file.name} (modernized)",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines)

    target_file.write_text(repaired_code, encoding="utf-8")
    print(f"[Worker Success] Applied verified AST patch to {target_file.name}")

    return PatchResult(
        success=True,
        modified_file=str(target_file),
        diff=diff_text,
    )