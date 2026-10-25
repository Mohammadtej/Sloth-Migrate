import difflib
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import sentry_sdk

from sloth_migrate.ast_guard import validate_python_code
from sloth_migrate.config import settings
from sloth_migrate.ecosystems.python_ecosystem import PythonEcosystem
from sloth_migrate.llm.client import gemma_client
from sloth_migrate.llm.prompts import SYSTEM_REFACTOR_PROMPT, USER_REFACTOR_TEMPLATE
from sloth_migrate.telemetry.sentry import init_telemetry, trace_span

console = Console()


def _display_diff(old_text: str, new_text: str, filename: str) -> None:
    """Renders a colorized unified diff between original and patched code."""
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
    """Prints the final summary table of the migration run."""
    table = Table(title="Migration Run Summary", border_style="green" if success else "red")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Status", "[green]SUCCESS (PASS)[/green]" if success else "[red]FAILED[/red]")
    table.add_row("Total Iterations", str(iterations))
    table.add_row("Files Modernized", str(len(modified_files)))
    for f in modified_files:
        table.add_row("Modified File", f.name)

    console.print(table)


async def run_generic_migration(
    target_dir: Path,
    target_pkg: str,
    target_ver: str,
) -> bool:
    """Executes the closed-loop dependency migration, AST repair, and test verification process."""
    init_telemetry()
    ecosystem = PythonEcosystem()

    console.print(
        Panel.fit(
            f"[bold green]🦥 SlothMigrate Driver[/bold green]\n"
            f"Target Directory: [yellow]{target_dir.resolve()}[/yellow]\n"
            f"Target Package:   [cyan]{target_pkg} >= {target_ver}[/cyan]\n"
            f"Inference Model:  [magenta]{settings.llm_model}[/magenta]",
            border_style="green",
        )
    )

    if not ecosystem.detect(target_dir):
        console.print("[red]❌ Target directory is not a recognized Python project.[/red]")
        return False

    with sentry_sdk.start_transaction(
        op="ai.migration",
        name=f"Migrate {target_pkg} to >={target_ver}",
    ):
        # Step 1: Bump Dependency in Manifest
        console.print(f"\n[bold blue]Step 1:[/bold blue] Bumping [cyan]{target_pkg}[/cyan] in manifest...")
        with trace_span("manifest.bump", op="ai.tool.manifest", data={"pkg": target_pkg, "version": target_ver}):
            bumped = ecosystem.bump_dependency(target_dir, target_pkg, target_ver)

        if bumped:
            console.print(f"  [green]✔ Updated manifest to {target_pkg}>={target_ver}[/green]")
        else:
            console.print("  [yellow]⚠ No matching entry in manifest; proceeding with environment update.[/yellow]")

        # Step 2: Sandbox / Pip Install
        console.print(f"  [cyan]Verifying/Installing {target_pkg}>={target_ver} in runtime environment...[/cyan]")
        with trace_span("pip.install", op="ai.tool.package_manager", data={"pkg": target_pkg}):
            installed, install_log = ecosystem.install_dependency(target_pkg, target_ver)

        if installed:
            console.print("  [green]✔ Environment package dependencies satisfied.[/green]")
        else:
            console.print(f"  [yellow]⚠ Package install note: {install_log.strip()[:200]}[/yellow]")

        # Step 3: Self-Healing Feedback Loop
        iteration = 0
        max_attempts = settings.max_repair_attempts
        files_modified: set[Path] = set()

        while iteration < max_attempts:
            iteration += 1
            console.print(
                f"\n[bold blue]Iteration {iteration}/{max_attempts}:[/bold blue] Running test suite against updated runtime..."
            )

            with trace_span("pytest.run", op="ai.tool.test_runner", data={"iteration": iteration}):
                exit_code, test_output = ecosystem.run_tests(target_dir)

            if exit_code == 0:
                console.print("\n[bold green]🎉 All tests passed cleanly![/bold green]")
                _print_summary(True, iteration, files_modified)
                sentry_sdk.flush(timeout=3.0)
                return True

            # Step 4: Parse failure trace
            failures = ecosystem.parse_traceback(test_output, target_dir)
            if not failures:
                if "collected 0 items" in test_output and "error" not in test_output.lower():
                    console.print("[red]✖ Tests failed: 0 tests collected. Test suite may be empty.[/red]")
                else:
                    console.print("[red]Could not isolate specific project files from pytest output.[/red]")
                console.print(Panel(test_output[-1200:], title="Raw Pytest Output", border_style="red"))
                break

            console.print("  [red]✖ Tests failed as expected due to breaking changes/deprecations.[/red]")
            console.print(f"  [yellow]Found {len(failures)} actionable failure point(s):[/yellow]")
            for f in failures:
                console.print(f"    • [cyan]{f.file_path.name}[/cyan] -> [red]{f.error_type}[/red]")

            # Step 5: Select primary failing target file
            primary_failure = failures[0]
            target_file = primary_failure.file_path

            if not target_file.exists():
                console.print(f"  [red]File {target_file} does not exist.[/red]")
                break

            original_code = target_file.read_text(encoding="utf-8")
            console.print(f"\n  [cyan]🤖 Asking Gemma to patch primary culprit: {target_file.name}...[/cyan]")

            user_prompt = USER_REFACTOR_TEMPLATE.format(
                traceback=primary_failure.raw_traceback,
                file_path=str(target_file.relative_to(target_dir)),
                line_number=primary_failure.line_number or "N/A",
                error_type=primary_failure.error_type,
                file_content=original_code,
            )

            try:
                with trace_span("gemma.generate_fix", op="ai.chat_completions", data={"target_file": target_file.name}):
                    repaired_code = await gemma_client.generate_fix(
                        system_prompt=SYSTEM_REFACTOR_PROMPT,
                        user_prompt=user_prompt,
                    )
            except Exception as e:
                console.print(f"  [red]LLM invocation error: {e}[/red]")
                sentry_sdk.capture_exception(e)
                return False

            if not repaired_code or repaired_code.strip() == original_code.strip():
                console.print(f"  [yellow]No syntax changes produced for {target_file.name}.[/yellow]")
                continue

            # Step 6: AST Validation Gate
            with trace_span("ast.validate", op="ai.tool.ast_guard", data={"file": target_file.name}):
                validation = validate_python_code(repaired_code, filename=target_file.name)

            if not validation.is_valid:
                console.print(
                    f"  [red]⚠ AST validation failed: {validation.error_message}. Rejecting patch to protect codebase.[/red]"
                )
                continue

            # Step 7: Apply Verified Patch
            _display_diff(original_code, repaired_code, target_file.name)
            target_file.write_text(repaired_code, encoding="utf-8")
            files_modified.add(target_file)
            console.print(f"  [green]✔ Applied AST-verified patch to {target_file.name}[/green]")

        console.print("\n[red]❌ Maximum repair attempts reached without achieving a green test suite.[/red]")
        _print_summary(False, iteration, files_modified)
        sentry_sdk.flush(timeout=3.0)
        return False