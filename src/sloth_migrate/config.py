from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for SlothMigrate runtime, LLM client, and workflows."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # LLM Inference Backend (Gemma)
    # -------------------------------------------------------------------------
    llm_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        description="Base URL for OpenAI-compatible inference endpoint.",
    )
    llm_model: str = Field(
        default="gemma-4-12b-it",
        description="Gemma model identifier to request.",
    )
    llm_api_key: str = Field(
        default="",
        description="API token (Google AI Studio, OpenRouter, or Droplet key).",
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Sampling temperature (lower = more deterministic code diffs).",
    )
    llm_max_tokens: int = Field(
        default=4096,
        description="Maximum token generation limit per patch request.",
    )

    # -------------------------------------------------------------------------
    # Temporal Durable Orchestration
    # -------------------------------------------------------------------------
    temporal_host: str = Field(
        default="localhost:7233",
        description="Host and port of the running Temporal server.",
    )
    temporal_namespace: str = Field(
        default="default",
        description="Temporal namespace for workflow registration.",
    )
    temporal_task_queue: str = Field(
        default="sloth-migrate-task-queue",
        description="Target queue where SlothMigrate workers listen.",
    )

    # -------------------------------------------------------------------------
    # Sentry Agent Tracing
    # -------------------------------------------------------------------------
    sentry_dsn: str = Field(
        default="",
        description="Sentry DSN for tracing tool spans, latency, and tokens.",
    )
    sentry_environment: str = Field(
        default="development",
        description="Deployment environment name reported to Sentry.",
    )
    sentry_traces_sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Transaction trace sampling rate.",
    )

    # -------------------------------------------------------------------------
    # Execution & Repair Sandbox Parameters
    # -------------------------------------------------------------------------
    max_repair_attempts: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max feedback cycles before flagging a manual review check.",
    )
    debug: bool = Field(
        default=False,
        description="Enable verbose stdout diagnostics during execution.",
    )


settings = Settings()