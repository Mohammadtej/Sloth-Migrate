"""Temporal Durable Workflow orchestrating SlothMigrate's self-healing loop."""

from datetime import timedelta
from pydantic import BaseModel
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
    modified_files: list[str]
    error_summary: str | None = None


@workflow.defn
class DependencyMigrationWorkflow:
    """Durable state machine executing the sequential migration and repair cycle."""

    @workflow.run
    async def run(self, input_data: MigrationWorkflowInput) -> MigrationWorkflowOutput:
        standard_retry = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=3,
        )

        # 1. Bump manifest & sandbox install
        await workflow.execute_activity(
            bump_and_install_activity,
            BumpParams(
                repo_path=input_data.repo_path,
                package=input_data.package,
                target_version=input_data.target_version,
            ),
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=standard_retry,
        )

        modified_files: set[str] = set()

        # 2. Sequential Durable Self-Healing Loop
        for iteration in range(1, input_data.max_attempts + 1):
            test_result = await workflow.execute_activity(
                run_tests_activity,
                TestRunParams(repo_path=input_data.repo_path),
                start_to_close_timeout=timedelta(minutes=2),
            )

            if test_result.exit_code == 0:
                return MigrationWorkflowOutput(
                    success=True,
                    iterations=iteration,
                    modified_files=list(modified_files),
                )

            if not test_result.failing_files:
                return MigrationWorkflowOutput(
                    success=False,
                    iterations=iteration,
                    modified_files=list(modified_files),
                    error_summary="Could not isolate failing files from test output.",
                )

            # Patch primary culprit
            primary_file = test_result.failing_files[0]
            patch_result = await workflow.execute_activity(
                generate_and_apply_patch_activity,
                PatchParams(
                    repo_path=input_data.repo_path,
                    target_file=primary_file,
                    raw_traceback=test_result.output[-2500:],
                ),
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=standard_retry,
            )

            if patch_result.success:
                modified_files.add(patch_result.modified_file)

        return MigrationWorkflowOutput(
            success=False,
            iterations=input_data.max_attempts,
            modified_files=list(modified_files),
            error_summary="Exceeded maximum repair attempts without green tests.",
        )