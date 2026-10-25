"""Atomic Temporal activities representing tool executions in SlothMigrate."""

from datetime import timedelta
from pathlib import Path
from pydantic import BaseModel
from temporalio import activity

from sloth_migrate.ast_guard import validate_python_code
from sloth_migrate.ecosystems.python_ecosystem import PythonEcosystem
from sloth_migrate.llm.client import gemma_client
from sloth_migrate.llm.prompts import SYSTEM_REFACTOR_PROMPT, USER_REFACTOR_TEMPLATE


class BumpParams(BaseModel):
    repo_path: str
    package: str
    target_version: str


class TestRunParams(BaseModel):
    repo_path: str


class TestRunResult(BaseModel):
    exit_code: int
    output: str
    failing_files: list[str]


class PatchParams(BaseModel):
    repo_path: str
    target_file: str
    raw_traceback: str


class PatchResult(BaseModel):
    success: bool
    modified_file: str
    diff: str
    error_message: str | None = None


@activity.defn
async def bump_and_install_activity(params: BumpParams) -> bool:
    """Activity: Bump manifest and update runtime sandbox environment."""
    repo_dir = Path(params.repo_path)
    ecosystem = PythonEcosystem()

    ecosystem.bump_dependency(repo_dir, params.package, params.target_version)
    installed, _ = ecosystem.install_dependency(params.package, params.target_version)
    return installed


@activity.defn
async def run_tests_activity(params: TestRunParams) -> TestRunResult:
    """Activity: Execute pytest in repository and parse failure trace."""
    repo_dir = Path(params.repo_path)
    ecosystem = PythonEcosystem()

    exit_code, output = ecosystem.run_tests(repo_dir)
    failures = ecosystem.parse_traceback(output, repo_dir)
    failing_files = [str(f.file_path) for f in failures]

    return TestRunResult(
        exit_code=exit_code,
        output=output,
        failing_files=failing_files,
    )


@activity.defn
async def generate_and_apply_patch_activity(params: PatchParams) -> PatchResult:
    """Activity: Prompt Gemma, AST-validate the patch, and write to disk."""
    repo_dir = Path(params.repo_path)
    target_file = Path(params.target_file)

    if not target_file.exists():
        return PatchResult(
            success=False,
            modified_file=str(target_file),
            diff="",
            error_message="Target file does not exist",
        )

    original_code = target_file.read_text(encoding="utf-8")
    user_prompt = USER_REFACTOR_TEMPLATE.format(
        traceback=params.raw_traceback,
        file_path=str(target_file.relative_to(repo_dir)),
        line_number="N/A",
        error_type="Deprecation / Breaking Change",
        file_content=original_code,
    )

    repaired_code = await gemma_client.generate_fix(
        system_prompt=SYSTEM_REFACTOR_PROMPT,
        user_prompt=user_prompt,
    )

    # AST validation gate
    validation = validate_python_code(repaired_code, filename=target_file.name)
    if not validation.is_valid:
        return PatchResult(
            success=False,
            modified_file=str(target_file),
            diff="",
            error_message=f"AST Validation failed: {validation.error_message}",
        )

    target_file.write_text(repaired_code, encoding="utf-8")
    return PatchResult(
        success=True,
        modified_file=str(target_file),
        diff=f"Patched {target_file.name}",
    )