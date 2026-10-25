import os
from pathlib import Path
import re
import subprocess
from sloth_migrate.ecosystems.base import BaseEcosystem, FailureContext


class PythonEcosystem(BaseEcosystem):
    name = "python"

    def detect(self, repo_dir: Path) -> bool:
        return (
            (repo_dir / "pyproject.toml").exists()
            or (repo_dir / "requirements.txt").exists()
            or (repo_dir / "setup.py").exists()
        )

    def bump_dependency(self, repo_dir: Path, package: str, target_version: str) -> bool:
        """Updates the version constraint in pyproject.toml or requirements.txt."""
        pyproject_path = repo_dir / "pyproject.toml"
        requirements_path = repo_dir / "requirements.txt"

        version_spec = f">={target_version}" if not target_version.startswith((">=", "==", "^")) else target_version

        # 1. Check pyproject.toml
        if pyproject_path.exists():
            content = pyproject_path.read_text(encoding="utf-8")
            # Matches "pydantic>=1.10.0" or "pydantic = '^1.0'"
            pattern = rf'("{re.escape(package)}[<>=~^!][^"]*"|"{re.escape(package)}")'
            if re.search(pattern, content):
                new_content = re.sub(pattern, f'"{package}{version_spec}"', content)
                pyproject_path.write_text(new_content, encoding="utf-8")
                return True

        # 2. Check requirements.txt
        if requirements_path.exists():
            lines = requirements_path.read_text(encoding="utf-8").splitlines()
            updated = False
            new_lines = []
            for line in lines:
                clean_line = line.strip()
                if clean_line.startswith(package) and (len(clean_line) == len(package) or clean_line[len(package)] in "=<>~"):
                    new_lines.append(f"{package}{version_spec}")
                    updated = True
                else:
                    new_lines.append(line)
            if updated:
                requirements_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return True

        return False

    def run_tests(self, repo_dir: Path) -> tuple[int, str]:
        """Executes pytest in the target repository directory, elevating deprecation warnings."""
        env = os.environ.copy()
        # Elevates deprecation warnings to catch soft breaks proactively
        cmd = [
            "pytest",
            "-v",
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_dir,
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
            )
            combined_output = f"{result.stdout}\n{result.stderr}"
            return result.returncode, combined_output
        except subprocess.TimeoutExpired:
            return 1, "Pytest test execution timed out after 60 seconds."
        except FileNotFoundError:
            return 1, "pytest executable not found in current environment."

    def parse_traceback(self, test_output: str, repo_dir: Path) -> list[FailureContext]:
        """Parses pytest output to extract failing file paths, lines, and error types."""
        failures: list[FailureContext] = []

        # Pattern 1: Standard Python exception lines (e.g., File "app.py", line 42, in <module>)
        frame_pattern = re.compile(
            r'File "([^"]+\.py)", line (\d+)(?:, in .*)?\n\s*(.*?)\n([A-Za-z0-9_]+Error|[A-Za-z0-9_]+Warning): (.*)',
            re.MULTILINE,
        )

        for match in frame_pattern.finditer(test_output):
            raw_path, line_str, code_snippet, err_type, err_msg = match.groups()
            candidate_path = Path(raw_path)
            if not candidate_path.is_absolute():
                candidate_path = repo_dir / candidate_path

            # Only target user project files, ignore test runners or virtualenvs
            if candidate_path.exists() and "site-packages" not in str(candidate_path):
                failures.append(
                    FailureContext(
                        file_path=candidate_path,
                        line_number=int(line_str),
                        error_type=err_type,
                        failure_message=err_msg.strip(),
                        raw_traceback=match.group(0),
                    )
                )

        # Pattern 2: Pytest Summary Failure headers (e.g. FAILED test_app.py::test_user - AttributeError: ...)
        summary_pattern = re.compile(r"FAILED\s+([^:]+\.py)::(\w+)\s+-\s+([A-Za-z0-9_]+Error): (.*)")
        for match in summary_pattern.finditer(test_output):
            file_str, test_func, err_type, err_msg = match.groups()
            candidate_path = repo_dir / file_str
            if candidate_path.exists() and not any(f.file_path == candidate_path for f in failures):
                failures.append(
                    FailureContext(
                        file_path=candidate_path,
                        line_number=None,
                        error_type=err_type,
                        failure_message=f"{test_func}: {err_msg.strip()}",
                        raw_traceback=test_output[-1500:],
                    )
                )

        return failures