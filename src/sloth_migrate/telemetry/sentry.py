"""Sentry Agent Tracing and observability instrumentation for SlothMigrate."""

from contextlib import contextmanager
from typing import Any, Generator
import sentry_sdk
from sentry_sdk.tracing import Span

from sloth_migrate.config import settings


def init_telemetry() -> bool:
    """Initializes Sentry SDK if SENTRY_DSN is configured in environment."""
    if not settings.sentry_dsn:
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        release="sloth-migrate@0.1.0",
        send_default_pii=False,
    )
    return True


@contextmanager
def trace_agent_action(
    action_name: str,
    op: str = "ai.tool",
    description: str | None = None,
    data: dict[str, Any] | None = None,
) -> Generator[Span | None, None, None]:
    """Context manager recording spans for agent actions, tool calls, and LLM queries."""
    if not settings.sentry_dsn:
        yield None
        return

    with sentry_sdk.start_span(op=op, description=description or action_name) as span:
        if data:
            for k, v in data.items():
                span.set_data(k, v)
        yield span