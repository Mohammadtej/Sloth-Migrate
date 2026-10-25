"""Sentry AI Agent Observability integration for SlothMigrate."""

from contextlib import contextmanager
from typing import Any, Generator
import sentry_sdk
from sentry_sdk.tracing import Span

from sloth_migrate.config import settings


def init_telemetry() -> bool:
    """Initializes Sentry SDK if SENTRY_DSN is configured in environment."""
    if not settings.sentry_dsn or not settings.sentry_dsn.strip():
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
def trace_span(
    name: str,
    op: str = "ai.tool",
    data: dict[str, Any] | None = None,
) -> Generator[Span | None, None, None]:
    """Records a granular child span within the active Sentry transaction."""
    if not settings.sentry_dsn or not settings.sentry_dsn.strip():
        yield None
        return

    with sentry_sdk.start_span(op=op, description=name) as span:
        if data:
            for key, val in data.items():
                span.set_data(key, val)
        yield span


# Alias for backward compatibility
trace_agent_action = trace_span