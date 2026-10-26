"""Temporal Durable Workflow orchestrating SlothMigrate's self-healing loop."""

from datetime import timedelta
from pydantic import BaseModel, Field
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sloth_migrate.workflows.activities import (
        BumpParams,
        PatchParams,
        TestRunParams,
        bump_and_install_activity,
        generate_and_apply_patch_activity,
        run_tests_activity,
    )


class MigrationWorkflowInput(BaseModel):
    repo_path: str
    package: str
    target_version: str
    max_attempts: int = 5


class MigrationWorkflowOutput(BaseModel):
    success: bool
    iterations: int
    modified_files: list[str] = Field(default_factory=list)
    diffs: list[str] = Field(default_factory=list)
    error_summary: str | None = None


@workflow.defn
class DependencyMigrationWorkflow:
    @workflow.run
    async def run(self, input_data: MigrationWorkflowInput) -> MigrationWorkflowOutput:
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=20),
            maximum_attempts=3,
        )

        # 1. Bump & Install
        await workflow.execute_activity(
            bump_and_install_activity,
            BumpParams(
                repo_path=input_data.repo_path,
                package=input_data.package,
                target_version=input_data.target_version,
            ),
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry_policy,
        )

        modified_files: set[str] = set()
        diffs: list[str] = []

        # 2. Iterative Healing Loop
        for iteration in range(1, input_data.max_attempts + 1):
            test_res = await workflow.execute_activity(
                run_tests_activity,
                TestRunParams(repo_path=input_data.repo_path),
                start_to_close_timeout=timedelta(minutes=2),
            )

            if test_res.exit_code == 0:
                return MigrationWorkflowOutput(
                    success=True,
                    iterations=iteration,
                    modified_files=list(modified_files),
                    diffs=diffs,
                )

            # Check for parsed actionable failure points
            if not test_res.failures:
                return MigrationWorkflowOutput(
                    success=False,
                    iterations=iteration,
                    modified_files=list(modified_files),
                    diffs=diffs,
                    error_summary="Could not detect actionable files in test failure.",
                )

            # Pick the primary failure point with full context
            primary_failure = test_res.failures[0]

            patch_res = await workflow.execute_activity(
                generate_and_apply_patch_activity,
                PatchParams(
                    repo_path=input_data.repo_path,
                    target_file=primary_failure.file_path,
                    line_number=primary_failure.line_number,
                    error_type=primary_failure.error_type,
                    raw_traceback=primary_failure.raw_traceback,
                ),
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=retry_policy,
            )

            if patch_res.success:
                modified_files.add(patch_res.modified_file)
                patch_diff = getattr(patch_res, "diff", "")
                if patch_diff:
                    diffs.append(patch_diff)

        return MigrationWorkflowOutput(
            success=False,
            iterations=input_data.max_attempts,
            modified_files=list(modified_files),
            diffs=diffs,
            error_summary="Max attempts reached without green tests.",
        )