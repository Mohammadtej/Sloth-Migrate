import os
from pathlib import Path
import re
import subprocess
import sys
from sloth_migrate.ecosystems.base import BaseEcosystem, FailureContext
import httpx
import tomli

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
        """Scans the repository for files mentioned in the test failure output."""
        failures: list[FailureContext] = []
        
        # 1. Discover all candidate python files in the target project
        project_files = [
            f for f in repo_dir.rglob("*.py")
            if not any(part in f.parts for part in [".venv", "venv", ".git", "__pycache__", "build", "dist"])
        ]

        # 2. Find which project files are actually mentioned in the output
        matched_files: list[Path] = []
        for file_path in project_files:
            rel_path = file_path.relative_to(repo_dir)
            
            # Check relative path (posix and windows formats) and just filename
            if (
                rel_path.as_posix() in test_output
                or str(rel_path) in test_output
                or file_path.name in test_output
            ):
                matched_files.append(file_path)

        if not matched_files:
            return []

        # 3. Prioritize source files over test files (fix root causes before tests)
        matched_files.sort(key=lambda p: 1 if p.name.startswith("test_") or p.name.endswith("_test.py") else 0)

        # 4. Construct contexts for the matched files
        for target_file in matched_files:
            failures.append(
                FailureContext(
                    file_path=target_file,
                    line_number=None,  # Not needed: Gemma identifies the line from the trace
                    error_type="Test Failure / Deprecation",
                    failure_message="Refer to the attached traceback",
                    raw_traceback=test_output[-2500:],  # Provide sufficient tail context
                )
            )

        return failures

    def list_dependencies(self, repo_dir: Path) -> dict[str, str]:
        """Discovers declared packages and their version constraints."""
        deps: dict[str, str] = {}
        pyproject = repo_dir / "pyproject.toml"
        requirements = repo_dir / "requirements.txt"

        if pyproject.exists():
            try:
                data = tomli.loads(pyproject.read_text(encoding="utf-8"))
                # Standard PEP 621 dependencies
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
        """Queries the official PyPI JSON API for the latest stable version."""
        url = f"https://pypi.org/pypi/{package_name}/json"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("info", {}).get("version")
        return None