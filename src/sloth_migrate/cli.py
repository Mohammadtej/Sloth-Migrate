import asyncio
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table

from sloth_migrate import __version__
from sloth_migrate.ecosystems.python_ecosystem import PythonEcosystem
from sloth_migrate.runner import run_generic_migration

app = typer.Typer(
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
        help="Target version to bump to (e.g. 2.0.0)",
    ),
    all_latest: bool = typer.Option(
        False,
        "--all-latest",
        help="Automatically bump all declared dependencies to their latest PyPI version",
    ),
):
    """Inspects dependencies and executes the self-healing migration workflow."""
    asyncio.run(_async_run(target_path, package, target_version, all_latest))


async def _async_run(
    target_path: Path,
    pkg_flag: Optional[str],
    ver_flag: Optional[str],
    all_flag: bool,
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
        success = await run_generic_migration(target_path, pkg, ver)
        if not success:
            console.print(f"[red]Halting further migrations due to unresolved failure on {pkg}.[/red]")
            break


if __name__ == "__main__":
    app()