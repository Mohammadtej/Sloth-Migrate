"""Temporal worker entry point for distributed SlothMigrate runs."""

import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

from sloth_migrate.config import settings
from sloth_migrate.workflows.activities import (
    bump_and_install_activity,
    generate_and_apply_patch_activity,
    run_tests_activity,
)
from sloth_migrate.workflows.migration_workflow import DependencyMigrationWorkflow


async def start_worker():
    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[DependencyMigrationWorkflow],
        activities=[
            bump_and_install_activity,
            run_tests_activity,
            generate_and_apply_patch_activity,
        ],
    )
    print(f"🦥 SlothMigrate Temporal Worker active on queue: '{settings.temporal_task_queue}'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(start_worker())