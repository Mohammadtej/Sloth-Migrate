#!/usr/bin/env python3
import asyncio
import difflib
from pathlib import Path
import shutil
import sys

# Ensure src/ is on sys.path when running as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Support UTF-8 output on Windows consoles
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sloth_migrate.config import settings
from sloth_migrate.ecosystems.python_ecosystem import PythonEcosystem
from sloth_migrate.llm.client import gemma_client
from sloth_migrate.llm.prompts import SYSTEM_REFACTOR_PROMPT, USER_REFACTOR_TEMPLATE
# from sloth_migrate.telemetry.sentry import init_telemetry

console = Console()


async def run_generic_migration(
    target_dir: Path,
    target_pkg: str,
    target_ver: str,
) -> bool:
    """Runs dependency bump + test + Gemma patch loop for ANY package."""
    # Logic remains identical:
    # 1. ecosystem.bump_dependency(target_dir, target_pkg, target_ver)
    # 2. Loop pytest -> if fail, grab target_file and send to Gemma
    # 3. Gemma refactors code to fix the traceback
    # init_telemetry()
    ecosystem = PythonEcosystem()

    console.print(
        Panel.fit(
            f"[bold green]🦥 SlothMigrate Driver[/bold green]\n"
            f"Target Directory: [yellow]{fixture_dir.resolve()}[/yellow]\n"
            f"Target Package:   [cyan]{target_pkg} >= {target_ver}[/cyan]\n"
            f"Inference Model:  [magenta]{settings.llm_model}[/magenta]",
            border_style="green",
        )
    )

    if not ecosystem.detect(fixture_dir):
        console.print("[red]❌ Target directory is not a recognized Python project.[/red]")
        return False

    # Step 1: Bump Dependency in Manifest
    console.print(f"\n[bold blue]Step 1:[/bold blue] Bumping [cyan]{target_pkg}[/cyan] in manifest...")
    bumped = ecosystem.bump_dependency(fixture_dir, target_pkg, target_ver)
    if bumped:
        console.print(f"  [green]✔ Updated manifest specification to {target_pkg}>={target_ver}[/green]")
    else:
        console.print("  [yellow]⚠ No matching entry found in manifest; proceeding with current environment.[/yellow]")

    # Step 2: The Self-Healing Feedback Loop
    iteration = 0
    max_attempts = settings.max_repair_attempts
    files_modified: set[Path] = set()

    console.print(f"Defined max attempts in the system {max_attempts}")

    while iteration < max_attempts:
        iteration += 1
        console.print(
            f"\n[bold blue]Iteration {iteration}/{max_attempts}:[/bold blue] Running test suite against updated runtime..."
        )

        exit_code, test_output = ecosystem.run_tests(fixture_dir)

        if exit_code == 0:
            console.print("\n[bold green]🎉 All tests passed cleanly![/bold green]")
            _print_summary(True, iteration, files_modified)
            return True

        console.print("  [red]✖ Tests failed as expected due to breaking changes/deprecations.[/red]")

        # Step 3: Parse Failure Traceback
        failures = ecosystem.parse_traceback(test_output, fixture_dir)
        if not failures:
            console.print("[red]Could not isolate specific project files from pytest output.[/red]")
            console.print(Panel(test_output[-1200:], title="Raw Pytest Output", border_style="red"))
            break

        console.print(f"  [yellow]Found {len(failures)} actionable failure point(s):[/yellow]")
        for f in failures:
            console.print(f"    • [cyan]{f.file_path.name}[/cyan]: Line {f.line_number} -> [red]{f.error_type}[/red]")

        # Step 4: Dispatch Repairs to Gemma
        for failure in failures:
            target_file = failure.file_path
            if not target_file.exists():
                continue

            original_code = target_file.read_text(encoding="utf-8")
            console.print(f"\n  [cyan]🤖 Asking Gemma to patch {target_file.name}...[/cyan]")

            user_prompt = USER_REFACTOR_TEMPLATE.format(
                traceback=failure.raw_traceback,
                file_path=str(target_file.relative_to(fixture_dir)),
                line_number=failure.line_number or "N/A",
                error_type=failure.error_type,
                file_content=original_code,
            )

            try:
                repaired_code = await gemma_client.generate_fix(
                    system_prompt=SYSTEM_REFACTOR_PROMPT,
                    user_prompt=user_prompt,
                )
            except Exception as e:
                console.print(f"  [red]LLM invocation error: {e}[/red]")
                return False

            if not repaired_code or repaired_code.strip() == original_code.strip():
                console.print(f"  [yellow]No syntax changes produced for {target_file.name}.[/yellow]")
                continue

            # Display Diff
            _display_diff(original_code, repaired_code, target_file.name)

            # Apply Patch
            target_file.write_text(repaired_code, encoding="utf-8")
            files_modified.add(target_file)
            console.print(f"  [green]✔ Applied unified patch to {target_file.name}[/green]")

    console.print("\n[red]❌ Maximum repair attempts reached without achieving a green test suite.[/red]")
    _print_summary(False, iteration, files_modified)
    return False


def _display_diff(old_text: str, new_text: str, filename: str) -> None:
    """Renders a clean unified terminal diff of the code changes."""
    diff = list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"a/{filename} (legacy)",
            tofile=f"b/{filename} (modernized)",
            lineterm="",
        )
    )
    if not diff:
        return

    colored_diff = []
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            colored_diff.append(f"[green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            colored_diff.append(f"[red]{line}[/red]")
        elif line.startswith("@"):
            colored_diff.append(f"[cyan]{line}[/cyan]")
        else:
            colored_diff.append(f"[dim]{line}[/dim]")

    console.print(Panel("\n".join(colored_diff[:40]), title=f"AST Diff: {filename}", border_style="blue"))


def _print_summary(success: bool, iterations: int, modified_files: set[Path]) -> None:
    """Prints a structured final report table."""
    table = Table(title="Migration Run Summary", border_style="green" if success else "red")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Status", "[green]SUCCESS (PASS)[/green]" if success else "[red]FAILED[/red]")
    table.add_row("Total Iterations", str(iterations))
    table.add_row("Files Modernized", str(len(modified_files)))
    for f in modified_files:
        table.add_row("Modified File", f.name)

    console.print(table)


if __name__ == "__main__":
    default_fixture = Path("tests/fixtures/legacy_python_project")
    if not default_fixture.exists():
        console.print(f"[red]Error: Fixture directory '{default_fixture}' not found.[/red]")
        sys.exit(1)

    success = asyncio.run(run_pydantic_migration(default_fixture))
    sys.exit(0 if success else 1)