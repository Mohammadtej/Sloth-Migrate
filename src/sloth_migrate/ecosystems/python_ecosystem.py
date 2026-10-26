"""Python ecosystem dependency manager and test execution harness."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore

from sloth_migrate.ecosystems.base import BaseEcosystem


@dataclass
class FailurePoint:
    file_path: Path
    line_number: Optional[int]
    error_type: str
    raw_traceback: str


class PythonEcosystem(BaseEcosystem):
    """Manages Python dependency manifests, sandbox package installations, and test runs."""

    def detect(self, repo_path: Path) -> bool:
        """Returns True if the folder contains a Python manifest."""
        return (
            (repo_path / "pyproject.toml").exists()
            or (repo_path / "requirements.txt").exists()
            or (repo_path / "setup.py").exists()
        )

    def list_dependencies(self, repo_path: Path) -> Dict[str, str]:
        """Extracts declared packages and version constraints from pyproject.toml or requirements.txt."""
        deps: Dict[str, str] = {}

        # 1. Try pyproject.toml
        pyproject_file = repo_path / "pyproject.toml"
        if pyproject_file.exists():
            try:
                content = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
                # PEP 621 dependencies
                project_deps = content.get("project", {}).get("dependencies", [])
                for item in project_deps:
                    pkg, constraint = self._parse_requirement_str(item)
                    if pkg:
                        deps[pkg] = constraint

                # Poetry dependencies
                poetry_deps = content.get("tool", {}).get("poetry", {}).get("dependencies", {})
                for pkg, constraint in poetry_deps.items():
                    if pkg.lower() != "python":
                        deps[pkg] = str(constraint)
            except Exception:
                pass

        # 2. Check requirements.txt
        req_file = repo_path / "requirements.txt"
        if req_file.exists():
            for line in req_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                pkg, constraint = self._parse_requirement_str(line)
                if pkg and pkg not in deps:
                    deps[pkg] = constraint

        return deps

    def bump_dependency(self, repo_path: Path, package: str, target_version: str) -> bool:
        """Rewrites the dependency constraint in pyproject.toml or requirements.txt."""
        normalized_pkg = package.lower()

        # 1. Check requirements.txt
        req_file = repo_path / "requirements.txt"
        if req_file.exists():
            lines = req_file.read_text(encoding="utf-8").splitlines()
            updated = False
            new_lines = []
            for line in lines:
                pkg_match = re.match(r"^([a-zA-Z0-9_\-\.]+)(.*)$", line.strip())
                if pkg_match and pkg_match.group(1).lower() == normalized_pkg:
                    new_lines.append(f"{package}>={target_version}")
                    updated = True
                else:
                    new_lines.append(line)
            if updated:
                req_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return True

        # 2. Check pyproject.toml
        pyproject_file = repo_path / "pyproject.toml"
        if pyproject_file.exists():
            text = pyproject_file.read_text(encoding="utf-8")
            pattern = re.compile(
                rf'(["\']?{re.escape(package)}["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])',
                re.IGNORECASE,
            )
            if pattern.search(text):
                new_text = pattern.sub(rf"\g<1>>={target_version}\g<3>", text)
                pyproject_file.write_text(new_text, encoding="utf-8")
                return True

        return False

    def install_dependency(self, package: str, target_version: str) -> Tuple[bool, str]:
        """Installs the target package version into the running Python environment."""
        specifier = f"{package}>={target_version}"
        cmd = [sys.executable, "-m", "pip", "install", specifier]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, res.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr or e.stdout

    def run_tests(self, repo_path: Path) -> Tuple[int, str]:
        """Executes pytest against the repo with deprecation warnings promoted to errors."""
        resolved_repo = repo_path.resolve()
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(resolved_repo),
            "-v",
            "-W",
            "error::DeprecationWarning",
            "-W",
            "error::FutureWarning",
        ]
        res = subprocess.run(cmd, cwd=str(resolved_repo), capture_output=True, text=True)
        combined_output = f"{res.stdout}\n{res.stderr}".strip()
        return res.returncode, combined_output

    def parse_traceback(self, output: str, repo_path: Path) -> List[FailurePoint]:
        """Isolates the failing repository file, line number, and error type from pytest output."""
        failures: List[FailurePoint] = []
        repo_path_resolved = repo_path.resolve()

        patterns = [
            re.compile(r"([a-zA-Z0-9_\-\.\\\/:]+\.py):(\d+):\s+in\s+([^\n\r]+)"),
            re.compile(r"([a-zA-Z0-9_\-\.\\\/:]+\.py):(\d+):"),
        ]

        found_candidates: List[Tuple[Path, int]] = []
        for line in output.splitlines():
            for pat in patterns:
                m = pat.search(line)
                if m:
                    file_str = m.group(1).strip()
                    line_no = int(m.group(2))
                    candidate_path = Path(file_str)
                    if not candidate_path.is_absolute():
                        candidate_path = (repo_path_resolved / candidate_path).resolve()
                    else:
                        candidate_path = candidate_path.resolve()

                    if repo_path_resolved in candidate_path.parents and ".venv" not in candidate_path.parts:
                        found_candidates.append((candidate_path, line_no))

        error_lines = [
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(("E ", "ERROR", "pydantic.errors."))
        ]
        error_summary = error_lines[-1] if error_lines else "Breaking Change / Deprecation"

        if found_candidates:
            target_file, target_line = found_candidates[-1]
            failures.append(
                FailurePoint(
                    file_path=target_file,
                    line_number=target_line,
                    error_type=error_summary,
                    raw_traceback=output[-3000:],
                )
            )

        return failures

    async def get_latest_pypi_version(self, package_name: str) -> Optional[str]:
        """Queries PyPI JSON API for the latest release."""
        url = f"https://pypi.org/pypi/{package_name}/json"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("info", {}).get("version")
        return None

    def _parse_requirement_str(self, req: str) -> Tuple[Optional[str], str]:
        """Helper to extract package name and constraint from string."""
        m = re.match(r"^([a-zA-Z0-9_\-\.]+)(.*)$", req.strip())
        if m:
            pkg = m.group(1)
            constraint = m.group(2).strip() or "latest"
            return pkg, constraint
        return None, ""