# SlothMigrate 🦥⚡

> **Autonomous, Durable Dependency Migration Agent powered by Google Gemma, Temporal, and Sentry.**

[![Hacktoberfest](https://img.shields.io/badge/Hacktoberfest-2026-ff7518.svg)](https://hacktoberfest.com/)
[![Model](https://img.shields.io/badge/LLM-Gemma%204--26B--A4B--IT-blue.svg)](https://ai.google.dev/)
[![Orchestration](https://img.shields.io/badge/Temporal-Durable%20Execution-black.svg)](https://temporal.io/)
[![Observability](https://img.shields.io/badge/Sentry-Agent%20Monitoring-purple.svg)](https://sentry.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 📖 Overview

Upgrading breaking major dependencies (such as **Pydantic v1 → v2**, SQLAlchemy 1.4 → 2.0, or modern typing conventions) is often avoided by development teams. Simple regex replacements fail to capture schema semantics, and large-language-model coding tools frequently hallucinate, strip critical classes, or generate invalid syntax.

**SlothMigrate** transforms breaking dependency upgrades into a deterministic, fault-tolerant self-healing loop:

1. **Detects & Bumps:** Inspects `pyproject.toml` (PEP 621 / Poetry) and `requirements.txt`, updates version constraints, and synchronizes the virtual environment.
2. **Executes Test Suite:** Runs `pytest` with `-W error::DeprecationWarning` to escalate deprecated APIs into actionable errors.
3. **Pinpoints Exact Failures:** Parses Python tracebacks to extract the exact target file, line number, and error message across platforms (Windows, Linux, macOS).
4. **Targeted Gemma Refactoring:** Leverages Google's `gemma-4-26b-a4b-it` with an engineering-focused prompt enforcing zero code truncation and strict public API preservation.
5. **AST Guard:** Validates generated code in-memory using Python's `ast.parse` and structural class diffing *before* anything touches the filesystem.
6. **Durable Orchestration:** Powered by Temporal workflows, ensuring migrations survive process crashes, rate limits, and network timeouts.
7. **End-to-End Tracing:** Sentry tracks workflow executions, LLM token performance, patch validations, and self-healing iterations.

---

## 🏗️ Architecture

```
                  ┌─────────────────────────────────────┐
                  │       SlothMigrate CLI (Typer)      │
                  │   sloth-migrate run --path ...      │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                ┌─────────────────────────────────────────┐
                │   Temporal Durable Workflow Engine      │
                │   (Automatic retries, state persistence)│
                └───────┬─────────────────────────┬───────┘
                        │                         │
     Activity 1         ▼                         ▼ Activity 3
┌───────────────────────────────┐     ┌────────────────────────────────┐
│ bump_and_install_activity     │     │ generate_and_apply_patch       │
│ - Manifest parsing            │     │ - Prompt formatting            │
│ - Dependency escalation       │     │ - Google Gemma 4-26B inference │
└───────────────┬───────────────┘     └───────────────┬────────────────┘
                │                                     │
     Activity 2 ▼                                     ▼
┌───────────────────────────────┐     ┌────────────────────────────────┐
│ run_tests_activity            │     │ AST Structural Guard           │
│ - pytest run with -W error    │     │ - Syntax verification          │
│ - PythonEcosystem traceback   │     │ - Class preservation checks    │
│   parsing (Windows/Posix)     │     │ - Safe unified diff writing    │
└───────────────────────────────┘     └────────────────────────────────┘
                │                                     │
                └─────────────── Iteration ◄──────────┘
                              (up to budget)
```

---

## ✨ Key Features

- **🛡️ In-Memory AST Guard:** Catches missing syntax, incomplete blocks, and dropped classes before disk writes occur.
- **🔄 Durable Healing Loops:** If a patch introduces a secondary error, Temporal resumes the workflow from the last verified checkpoint rather than restarting.
- **🖥️ Cross-Platform Traceback Engine:** Custom regex resolution handles absolute paths, Windows drive letters (`C:\...`), and POSIX paths.
- **📊 Real-Time Rich UI:** Live terminal status updates, syntax-highlighted unified diffs, and iteration summaries.
- **🔍 Full Sentry Telemetry:** Distributed spans for test runs, LLM latency, and self-healing activity cycles.

---

## 🚀 Getting Started

### Prerequisites

- **Python:** 3.10 or higher
- **Temporal Server:** Local development CLI or remote cluster ([Temporal CLI Quickstart](https://docs.temporal.io/cli))
- **Google AI Studio API Key:** For Gemma access ([Get API Key](https://aistudio.google.com/))
- **Sentry DSN:** Optional for monitoring ([sentry.io](https://sentry.io))

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/Sloth-Migrate.git
cd Sloth-Migrate

# 2. Create and activate a virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 3. Install in editable mode with development dependencies
pip install -e .
```

### Environment Configuration

Create a `.env` file in the project root:

```env
# Google Gemini / Gemma API
GEMMA_API_KEY="your-google-ai-studio-api-key"
GEMMA_MODEL_NAME="models/gemma-4-26b-a4b-it"

# Temporal Configuration
TEMPORAL_HOST="localhost:7233"
TEMPORAL_TASK_QUEUE="sloth-migrate-task-queue"

# Sentry Monitoring (Optional)
SENTRY_DSN="your-sentry-dsn"
```

---

## 🏃 Running SlothMigrate

### 1. Start the Temporal Development Server

In a dedicated terminal:

```bash
temporal server start-dev
```
The Temporal Web UI will be accessible at [http://localhost:8233](http://localhost:8233).

### 2. Launch the SlothMigrate Temporal Worker

In a second terminal (inside `.venv`):

```bash
python -m sloth_migrate.workflows.worker
```

### 3. Run a Migration

In a third terminal, target a legacy repository:

```bash
sloth-migrate run \
  --path ../target-project \
  --package pydantic \
  --version 2.14.1 \
  --durable
```

#### CLI Options

| Option | Flag | Description | Default |
|---|---|---|---|
| `--path` | `-p` | Path to target project repository | Required |
| `--package` | `-pkg` | Dependency to upgrade | Required |
| `--version` | `-v` | Target package version | `latest` |
| `--durable` | `-d` | Execute via Temporal durable workflow | `True` |
| `--max-iterations` | `-i` | Maximum self-healing loops | `5` |

---

## 🧪 Testing

Run unit and integration test suites:

```bash
# Run all tests
pytest

# Run tests with deprecation escalation
pytest -W error::DeprecationWarning
```

---

## 🏆 Challenge & Hackathon Alignment

SlothMigrate was engineered for the **Hacktoberfest Challenge**, addressing key partner requirements:

- **Google Gemma:** Uses `gemma-4-26b-a4b-it` via Google GenAI for AST-constrained AST refactoring.
- **Temporal:** Orchestrates state machine checkpoints, handles worker crashes, and provides verifiable activity timelines.
- **Sentry:** Captures activity latencies, LLM call spans, and unexpected syntax errors across execution cycles.

---

## 📜 License

Distributed under the [MIT License](LICENSE).