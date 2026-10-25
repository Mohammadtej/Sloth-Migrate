from abc import ABC, abstractmethod
from pathlib import Path
from pydantic import BaseModel, Field


class FailureContext(BaseModel):
    """Structured details of a failed test assertion, import, or runtime error."""
    file_path: Path
    line_number: int | None = None
    error_type: str
    failure_message: str
    raw_traceback: str


class MigrationResult(BaseModel):
    """Execution status returned after running test iterations."""
    success: bool
    exit_code: int
    iterations: int = 0
    modified_files: list[Path] = Field(default_factory=list)
    remaining_failures: list[FailureContext] = Field(default_factory=list)


class BaseEcosystem(ABC):
    """Abstract interface for multi-language ecosystem adapters."""
    name: str

    @abstractmethod
    def detect(self, repo_dir: Path) -> bool:
        """Detects if the repo belongs to this ecosystem."""
        pass

    @abstractmethod
    def bump_dependency(self, repo_dir: Path, package: str, target_version: str) -> bool:
        """Updates the dependency declaration in manifest files."""
        pass

    @abstractmethod
    def run_tests(self, repo_dir: Path) -> tuple[int, str]:
        """Runs the test suite and captures exit code and output."""
        pass

    @abstractmethod
    def parse_traceback(self, test_output: str, repo_dir: Path) -> list[FailureContext]:
        """Extracts structured file failures from raw test stdout/stderr."""
        pass