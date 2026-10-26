"""Command Line Interface for SlothMigrate."""

import asyncio
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from temporalio.client import Client

from sloth_migrate import __version__
from sloth_migrate.config import settings
from sloth_migrate.ecosystems.python_ecosystem import PythonEcosystem
from sloth_migrate.runner import run_generic_migration
from sloth_migrate.workflows.migration_workflow import (
    DependencyMigrationWorkflow,
    MigrationWorkflowInput,
)

from temporalio.contrib.pydantic import pydantic_data_converter


app = typer.Typer(
    name="sloth-migrate",
    help="🦥 SlothMigrate - Autonomous Dependency Migration Engine",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main():
    """SlothMigrate CLI entrypoint."""
    pass


@app.command("version")
def version():
    """Show the current SlothMigrate version."""
    console.print(f"[bold green]SlothMigrate[/bold green] version: {__version__}")


@app.command("run")
def run(
    target_path: Path = typer.Option(
        Path("."),
        "--path",
        "-p",
        help="Path to the repository to migrate",
    ),
    package: Optional[str] = typer.Option(
        None,
        "--package",
        "-k",
        help="Specific package to bump (non-interactive mode)",
    ),
    target_version: Optional[str] = typer.Option(
        None,
        "--version",
        "-v",
        help="Target version to bump to (e.g. 2.14.1)",
    ),
    all_latest: bool = typer.Option(
        False,
        "--all-latest",
        help="Automatically bump all declared dependencies to their latest PyPI version",
    ),
    durable: bool = typer.Option(
        False,
        "--durable",
        "-d",
        help="Execute as a Temporal durable workflow",
    ),
):
    """Inspects dependencies and executes the self-healing migration workflow."""
    asyncio.run(_async_run(target_path, package, target_version, all_latest, durable))


async def _async_run(
    target_path: Path,
    pkg_flag: Optional[str],
    ver_flag: Optional[str],
    all_flag: bool,
    durable: bool,
):
    ecosystem = PythonEcosystem()
    target_path = target_path.resolve()

    if not ecosystem.detect(target_path):
        console.print(f"[red]❌ No recognized manifest found at {target_path}[/red]")
        raise typer.Exit(code=1)

    deps = ecosystem.list_dependencies(target_path)
    if not deps:
        console.print("[yellow]⚠ No declared dependencies detected in project manifest.[/yellow]")
        raise typer.Exit()

    # Display detected packages
    table = Table(title="Detected Dependencies", border_style="cyan")
    table.add_column("Package", style="bold green")
    table.add_column("Current Constraint", style="yellow")
    for name, constraint in deps.items():
        table.add_row(name, constraint)
    console.print(table)

    migrations_to_run: list[tuple[str, str]] = []

    # Case 1: Direct CLI arguments passed
    if pkg_flag and ver_flag:
        migrations_to_run.append((pkg_flag, ver_flag))

    # Case 2: Batch upgrade flag
    elif all_flag:
        console.print("\n[cyan]Fetching latest PyPI versions for all packages...[/cyan]")
        for name in deps:
            latest = await ecosystem.get_latest_pypi_version(name)
            if latest:
                migrations_to_run.append((name, latest))
            else:
                console.print(f"[dim]Could not resolve latest version for {name}[/dim]")

    # Case 3: Interactive Menu
    else:
        console.print("\n[bold]Migration Strategy Options:[/bold]")
        console.print("  [1] Bump a single package (specify target version)")
        console.print("  [2] Upgrade all packages to their latest stable version on PyPI")

        choice = Prompt.ask("Choose an option", choices=["1", "2"], default="1")

        if choice == "1":
            pkg_name = Prompt.ask("Enter package name", choices=list(deps.keys()))
            latest_suggested = await ecosystem.get_latest_pypi_version(pkg_name)
            ver = Prompt.ask(
                f"Enter target version for [green]{pkg_name}[/green]",
                default=latest_suggested or "latest",
            )
            migrations_to_run.append((pkg_name, ver))
        else:
            with console.status("Checking PyPI for latest releases..."):
                for name in deps:
                    latest = await ecosystem.get_latest_pypi_version(name)
                    if latest:
                        migrations_to_run.append((name, latest))

    # Review planned bumps
    console.print(f"\n[bold green]Planned Migrations ({len(migrations_to_run)}):[/bold green]")
    for pkg, ver in migrations_to_run:
        console.print(f"  • {pkg} ➔ [bold cyan]>={ver}[/bold cyan]")

    if not Confirm.ask("\nProceed with migration execution?", default=True):
        console.print("[yellow]Migration cancelled by user.[/yellow]")
        return

    # Execute sequentially
    for pkg, ver in migrations_to_run:
        console.print(f"\n[bold magenta]=== Starting Migration: {pkg} >= {ver} ===[/bold magenta]")

        if durable:
            console.print("[cyan]Submitting migration as durable Temporal workflow...[/cyan]")
            client = await Client.connect(
                settings.temporal_host,
                namespace=settings.temporal_namespace,
                data_converter=pydantic_data_converter,
            )
            clean_ver = ver.replace(".", "-").replace(">", "").replace("=", "").replace("<", "")
            workflow_id = f"sloth-migrate-{pkg}-{clean_ver}"

            handle = await client.start_workflow(
                DependencyMigrationWorkflow.run,
                MigrationWorkflowInput(
                    repo_path=str(target_path),
                    package=pkg,
                    target_version=ver,
                ),
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
            )

            console.print(f"[green]✔ Workflow initiated! ID:[/green] [bold]{handle.id}[/bold]")
            console.print(
                f"Live Web UI: [underline cyan]http://localhost:8233/namespaces/{settings.temporal_namespace}/workflows/{handle.id}[/underline cyan]"
            )

            with console.status("[bold green]Temporal durable execution in progress...[/bold green]"):
                result = await handle.result()

            if result.success:
                console.print(
                    f"\n[bold green]🎉 Temporal workflow succeeded in {result.iterations} iteration(s)![/bold green]"
                )

                diff_list = getattr(result, "diffs", [])
                if diff_list:
                    for patch_diff in diff_list:
                        colored_lines = []
                        for line in patch_diff.splitlines():
                            if line.startswith("+") and not line.startswith("+++"):
                                colored_lines.append(f"[green]{line}[/green]")
                            elif line.startswith("-") and not line.startswith("---"):
                                colored_lines.append(f"[red]{line}[/red]")
                            elif line.startswith("@"):
                                colored_lines.append(f"[cyan]{line}[/cyan]")
                            else:
                                colored_lines.append(f"[dim]{line}[/dim]")
                        console.print(Panel("\n".join(colored_lines[:45]), title="Applied Unified Patch", border_style="blue"))
                
                # Render clean summary table
                summary_table = Table(title="Durable Migration Summary", border_style="green")
                summary_table.add_column("Package", style="bold")
                summary_table.add_column("Iterations", style="cyan")
                summary_table.add_column("Files Modernized", style="yellow")
                summary_table.add_row(
                    f"{pkg} >= {ver}",
                    str(result.iterations),
                    "\n".join(Path(f).name for f in result.modified_files) or "None",
                )
                console.print(summary_table)
            else:
                console.print(f"\n[red]❌ Temporal workflow finished without success: {result.error_summary}[/red]")
                break
        else:
            success = await run_generic_migration(target_path, pkg, ver)
            if not success:
                console.print(f"[red]Halting further migrations due to unresolved failure on {pkg}.[/red]")
                break


if __name__ == "__main__":
    app()