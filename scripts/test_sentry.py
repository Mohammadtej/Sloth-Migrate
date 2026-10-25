#!/usr/bin/env python3
import time
from rich.console import Console
import sentry_sdk

from sloth_migrate.telemetry.sentry import init_telemetry, trace_span

console = Console()

if __name__ == "__main__":
    console.print("[cyan]Initializing Sentry connection...[/cyan]")
    is_active = init_telemetry()

    if not is_active:
        console.print("[red]❌ SENTRY_DSN is not configured in .env[/red]")
        exit(1)

    console.print("[green]✔ Telemetry initialized. Sending synthetic agent trace...[/green]")

    # Start a parent transaction matching an agent run
    with sentry_sdk.start_transaction(
        op="ai.agent.run",
        name="SlothMigrate Verification Run",
    ):
        with trace_span(
            "pytest.run_tests",
            op="ai.tool.test_runner",
            data={"target": "legacy_python_project", "exit_code": 1},
        ):
            time.sleep(0.2)

        with trace_span(
            "gemma.ast_patch",
            op="ai.chat_completions",
            data={
                "ai.model_id": "gemma-4-26b-a4b-it",
                "ai.prompt_tokens": 340,
                "ai.completion_tokens": 120,
            },
        ):
            time.sleep(0.3)

        with trace_span(
            "ast.validation",
            op="ai.tool.validator",
            data={"status": "valid", "file": "app.py"},
        ):
            time.sleep(0.1)

    # Force immediate delivery to Sentry before exit
    sentry_sdk.flush(timeout=5.0)
    console.print("[bold green]🎉 Telemetry event flushed successfully![/bold green]")
    console.print("Check your project's [bold cyan]Performance / Traces[/bold cyan] tab on sentry.io.")