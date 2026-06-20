"""Workspace scanner — find directories that contain a package manifest.

Each manifest-bearing directory is a workspace. Detection is conservative:
we don't try to interpret npm/pnpm/yarn workspace metadata, ``go.work``, or
``[workspace]`` Cargo tables. The codebase / per-repo LLM passes can refine.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sdk.indexer.db.workspaces import RepositoryWorkspace

# Manifest filename → (package_manager, dominant_language).
MANIFEST_TO_PM_LANG: Dict[str, Tuple[str, str]] = {
    "package.json": ("npm", "javascript"),
    "pnpm-workspace.yaml": ("pnpm", "javascript"),
    "yarn.lock": ("yarn", "javascript"),
    "pnpm-lock.yaml": ("pnpm", "javascript"),
    "package-lock.json": ("npm", "javascript"),
    "pyproject.toml": ("poetry", "python"),  # may be uv/poetry/pep621 — refined below
    "setup.py": ("pip", "python"),
    "setup.cfg": ("pip", "python"),
    "Pipfile": ("pip", "python"),
    "go.mod": ("go_modules", "go"),
    "Cargo.toml": ("cargo", "rust"),
    "pom.xml": ("maven", "java"),
    "build.gradle": ("gradle", "java"),
    "build.gradle.kts": ("gradle", "kotlin"),
    "Gemfile": ("bundler", "ruby"),
    "composer.json": ("composer", "php"),
    "Chart.yaml": ("helm", ""),
    "Berksfile": ("chef", "ruby"),
    "metadata.rb": ("chef", "ruby"),
    "Policyfile.rb": ("chef", "ruby"),
}

REQUIREMENTS_PREFIX = "requirements"


def scan_workspaces(
    files: list[tuple[str, int]], repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryWorkspace]:
    by_dir: Dict[str, List[str]] = defaultdict(list)
    for rel, _ in files:
        name = rel.rsplit("/", 1)[-1]
        dirpath = rel.rsplit("/", 1)[0] if "/" in rel else "."

        if name in MANIFEST_TO_PM_LANG:
            by_dir[dirpath].append(name)
        elif name.startswith(REQUIREMENTS_PREFIX) and name.endswith(".txt"):
            by_dir[dirpath].append(name)

    rows: List[RepositoryWorkspace] = []
    for dirpath, manifests in by_dir.items():
        pm = _pick_pm(manifests, repo_dir, dirpath)
        lang = _pick_language(manifests)
        rows.append(
            RepositoryWorkspace(
                user_id=user_id,
                repository_name=repository_name,
                workspace_path=dirpath,
                manifest_files=sorted(manifests),
                detected_language=lang,
                detected_package_manager=pm,
                evidence=[
                    {"kind": "manifest", "path": f"{dirpath}/{m}" if dirpath != "." else m}
                    for m in manifests
                ],
            )
        )
    return rows


def _pick_pm(
    manifests: List[str], repo_dir: Path | str, dirpath: str
) -> Optional[str]:
    """Pick the dominant package manager when multiple manifests coexist.

    Lockfile presence wins (most specific). For ``pyproject.toml`` we probe
    the contents to distinguish poetry / uv / pep621 so the dependency
    parser doesn't have to re-do the work.
    """
    name_set = set(manifests)

    if "pnpm-lock.yaml" in name_set or "pnpm-workspace.yaml" in name_set:
        return "pnpm"
    if "yarn.lock" in name_set:
        return "yarn"
    if "package-lock.json" in name_set:
        return "npm"
    if "package.json" in name_set:
        return "npm"
    if "Cargo.toml" in name_set:
        return "cargo"
    if "go.mod" in name_set:
        return "go_modules"
    if "Pipfile" in name_set:
        return "pip"
    if "pyproject.toml" in name_set:
        return _detect_python_pm(Path(repo_dir) / dirpath / "pyproject.toml")
    if any(m.startswith(REQUIREMENTS_PREFIX) and m.endswith(".txt") for m in manifests):
        return "pip"
    if "Gemfile" in name_set:
        return "bundler"
    if "composer.json" in name_set:
        return "composer"
    if "pom.xml" in name_set:
        return "maven"
    if "build.gradle" in name_set or "build.gradle.kts" in name_set:
        return "gradle"
    if "Chart.yaml" in name_set:
        return "helm"
    if name_set & {"Berksfile", "metadata.rb", "Policyfile.rb"}:
        return "chef"
    return None


def _detect_python_pm(pyproject_path: Path) -> str:
    try:
        import tomllib

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return "pip"

    tool = data.get("tool", {}) or {}
    if "poetry" in tool:
        return "poetry"
    if "uv" in tool or _has_uv_workspace(data) or "dependency-groups" in data:
        return "uv"
    if "project" in data:
        return "uv"  # PEP 621 — caller can revise via uv.lock presence
    return "pip"


def _has_uv_workspace(data: dict) -> bool:
    return bool((data.get("tool", {}) or {}).get("uv", {}).get("workspace"))


def _pick_language(manifests: List[str]) -> Optional[str]:
    for m in manifests:
        info = MANIFEST_TO_PM_LANG.get(m)
        if info and info[1]:
            return info[1]
    return None
