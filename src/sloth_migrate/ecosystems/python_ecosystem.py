import os
from pathlib import Path
import re
import subprocess
import sys
import httpx

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from sloth_migrate.ecosystems.base import BaseEcosystem, FailureContext


class PythonEcosystem(BaseEcosystem):
    name = "python"

    def detect(self, repo_dir: Path) -> bool:
        return (
            (repo_dir / "pyproject.toml").exists()
            or (repo_dir / "requirements.txt").exists()
            or (repo_dir / "setup.py").exists()
        )

    def list_dependencies(self, repo_dir: Path) -> dict[str, str]:
        """Discovers declared packages and their version constraints."""
        deps: dict[str, str] = {}
        pyproject = repo_dir / "pyproject.toml"
        requirements = repo_dir / "requirements.txt"

        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                project_deps = data.get("project", {}).get("dependencies", [])
                for dep in project_deps:
                    match = re.match(r"^([a-zA-Z0-9_\-]+)(.*)$", dep.strip())
                    if match:
                        deps[match.group(1)] = match.group(2).strip() or "unconstrained"
            except Exception:
                pass

        if requirements.exists() and not deps:
            for line in requirements.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "-")):
                    match = re.match(r"^([a-zA-Z0-9_\-]+)(.*)$", line)
                    if match:
                        deps[match.group(1)] = match.group(2).strip() or "unconstrained"

        return deps

    async def get_latest_pypi_version(self, package_name: str) -> str | None:
        """Queries the official PyPI JSON API for the latest stable release."""
        url = f"https://pypi.org/pypi/{package_name}/json"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("info", {}).get("version")
        except Exception:
            pass
        return None

    def bump_dependency(self, repo_dir: Path, package: str, target_version: str) -> bool:
        """Updates the version constraint in pyproject.toml or requirements.txt."""
        pyproject_path = repo_dir / "pyproject.toml"
        requirements_path = repo_dir / "requirements.txt"

        version_spec = (
            f">={target_version}"
            if not target_version.startswith((">=", "==", "^", "~="))
            else target_version
        )

        # 1. Update pyproject.toml
        if pyproject_path.exists():
            content = pyproject_path.read_text(encoding="utf-8")
            pattern = rf'("{re.escape(package)}[<>=~^!][^"]*"|"{re.escape(package)}")'
            if re.search(pattern, content):
                new_content = re.sub(pattern, f'"{package}{version_spec}"', content)
                pyproject_path.write_text(new_content, encoding="utf-8")
                return True

        # 2. Update requirements.txt
        if requirements_path.exists():
            lines = requirements_path.read_text(encoding="utf-8").splitlines()
            updated = False
            new_lines = []
            for line in lines:
                clean_line = line.strip()
                if clean_line.startswith(package) and (
                    len(clean_line) == len(package) or clean_line[len(package)] in "=<>~"
                ):
                    new_lines.append(f"{package}{version_spec}")
                    updated = True
                else:
                    new_lines.append(line)
            if updated:
                requirements_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return True

        return False

    def install_dependency(self, package: str, version: str) -> tuple[bool, str]:
        """Upgrades the target package in the active Python environment."""
        version_spec = (
            f">={version}"
            if not version.startswith((">=", "==", "^", "~="))
            else version
        )
        target_spec = f"{package}{version_spec}"
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", target_spec]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            combined_output = f"{result.stdout}\n{result.stderr}"
            return result.returncode == 0, combined_output
        except subprocess.TimeoutExpired:
            return False, "pip install timed out after 120 seconds."
        except Exception as e:
            return False, f"Failed to execute pip install: {e}"

    def run_tests(self, repo_dir: Path) -> tuple[int, str]:
        """Runs pytest with deprecation warnings elevated to errors."""
        env = os.environ.copy()
        cmd = [
            sys.executable,
            "-m",
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
        """Locates project files referenced in test output and sorts by implementation priority."""
        failures: list[FailureContext] = []

        # Find all Python files in the target project, ignoring venvs and caches
        project_files = [
            f
            for f in repo_dir.rglob("*.py")
            if not any(part in f.parts for part in [".venv", "venv", ".git", "__pycache__", "build", "dist"])
        ]

        matched_files: list[Path] = []
        for file_path in project_files:
            rel_path = file_path.relative_to(repo_dir)
            if (
                rel_path.as_posix() in test_output
                or str(rel_path) in test_output
                or file_path.name in test_output
            ):
                matched_files.append(file_path)

        if not matched_files:
            return []

        # Prioritize implementation files over test files
        matched_files.sort(
            key=lambda p: 1 if p.name.startswith("test_") or p.name.endswith("_test.py") else 0
        )

        for target_file in matched_files:
            failures.append(
                FailureContext(
                    file_path=target_file,
                    line_number=None,
                    error_type="Test Failure / Deprecation",
                    failure_message="See traceback context",
                    raw_traceback=test_output[-2500:],
                )
            )

        return failures