import asyncio
from rich.console import Console
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from sloth_migrate.config import settings
from sloth_migrate.workflows.activities import (
    bump_and_install_activity,
    generate_and_apply_patch_activity,
    run_tests_activity,
)
from sloth_migrate.workflows.migration_workflow import DependencyMigrationWorkflow

console = Console()


async def run_worker():
    console.print(f"[cyan]Connecting to Temporal host at [bold]{settings.temporal_host}[/bold]...[/cyan]")
    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
    )

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

    console.print(
        f"[bold green]✔ SlothMigrate Temporal Worker listening on queue: [cyan]'{settings.temporal_task_queue}'[/cyan][/bold green]"
    )
    console.print("[dim]Press Ctrl+C to stop worker.[/dim]")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())