"""Dependency scanner — parse package manifests across supported ecosystems.

Supported in this pass:
  - pip (requirements*.txt)
  - poetry (pyproject.toml [tool.poetry.*])
  - uv / pep621 (pyproject.toml [project.dependencies], [dependency-groups])
  - npm / yarn / pnpm (package.json)
  - go_modules (go.mod)
  - cargo (Cargo.toml)
  - helm (Chart.yaml dependencies)
  - chef (Berksfile cookbooks)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, List, Optional

from ..db.dependencies import RepositoryDependency
from ..db.workspaces import RepositoryWorkspace

logger = logging.getLogger(__name__)


def scan_dependencies(
    repo_dir: Path | str,
    user_id: str,
    repository_name: str,
    workspaces: Iterable[RepositoryWorkspace],
) -> List[RepositoryDependency]:
    """Run every applicable parser per workspace.

    A workspace may have multiple ecosystems coexisting (e.g. ``package.json``
    next to ``go.mod``). ``RepositoryWorkspace.detected_package_manager`` is
    only a hint; we inspect file presence directly.
    """
    rows: List[RepositoryDependency] = []
    for ws in workspaces:
        ws_dir = Path(repo_dir) / ("" if ws.workspace_path == "." else ws.workspace_path)

        if (ws_dir / "package.json").exists():
            rows.extend(_parse_package_json(ws_dir, ws, user_id, repository_name))
        if (ws_dir / "go.mod").exists():
            rows.extend(_parse_go_mod(ws_dir, ws, user_id, repository_name))
        if (ws_dir / "Cargo.toml").exists():
            rows.extend(_parse_cargo_toml(ws_dir, ws, user_id, repository_name))

        has_pyproject = (ws_dir / "pyproject.toml").exists()
        has_requirements = bool(list(ws_dir.glob("requirements*.txt")))
        if has_pyproject or has_requirements:
            python_pm = ws.detected_package_manager if ws.detected_package_manager in {"poetry", "uv", "pip"} else "pip"
            rows.extend(_parse_python(ws_dir, ws, user_id, repository_name, python_pm))

        if (ws_dir / "Chart.yaml").exists():
            rows.extend(_parse_chart_yaml(ws_dir, ws, user_id, repository_name))
        if (ws_dir / "Berksfile").exists():
            rows.extend(_parse_berksfile(ws_dir, ws, user_id, repository_name))
        if (ws_dir / "metadata.rb").exists():
            rows.extend(_parse_chef_metadata(ws_dir, ws, user_id, repository_name))
    return rows


# -- Python ----------------------------------------------------------------

REQ_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*"
    r"(?P<extras>\[[^\]]+\])?\s*"
    r"(?P<spec>[<>=!~].*)?$"
)


def _parse_python(
    ws_dir: Path,
    ws: RepositoryWorkspace,
    user_id: str,
    repository_name: str,
    pm_hint: str,
) -> List[RepositoryDependency]:
    rows: List[RepositoryDependency] = []
    pyproject = ws_dir / "pyproject.toml"
    if pyproject.exists():
        rows.extend(_parse_pyproject(pyproject, ws, user_id, repository_name, pm_hint))

    # requirements*.txt — always treat as pip even alongside poetry/uv.
    for path in sorted(ws_dir.glob("requirements*.txt")):
        rows.extend(_parse_requirements_txt(path, ws, user_id, repository_name))

    return rows


def _parse_pyproject(
    path: Path,
    ws: RepositoryWorkspace,
    user_id: str,
    repository_name: str,
    pm_hint: str,
) -> List[RepositoryDependency]:
    try:
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("Skipping pyproject %s: %s", path, exc)
        return []

    rows: List[RepositoryDependency] = []
    rel_source = _rel(path, ws)

    poetry = (data.get("tool", {}) or {}).get("poetry", {}) or {}
    if poetry:
        for name, spec in (poetry.get("dependencies") or {}).items():
            if name.lower() == "python":
                continue
            rows.append(
                _make_dep(
                    user_id, repository_name, ws, "poetry", name,
                    _stringify_poetry_spec(spec), rel_source, "runtime",
                )
            )
        for name, spec in (poetry.get("dev-dependencies") or {}).items():
            rows.append(
                _make_dep(
                    user_id, repository_name, ws, "poetry", name,
                    _stringify_poetry_spec(spec), rel_source, "dev",
                )
            )
        for group_name, group in (poetry.get("group") or {}).items():
            for name, spec in (group.get("dependencies") or {}).items():
                rows.append(
                    _make_dep(
                        user_id, repository_name, ws, "poetry", name,
                        _stringify_poetry_spec(spec), rel_source, group_name,
                    )
                )

    project = data.get("project", {}) or {}
    pep621_pm = "uv" if pm_hint == "uv" else "pip"
    for raw in project.get("dependencies", []) or []:
        parsed = _parse_pep508(raw)
        if not parsed:
            continue
        name, spec = parsed
        rows.append(
            _make_dep(
                user_id, repository_name, ws, pep621_pm, name, spec,
                rel_source, "runtime",
            )
        )
    for group_name, items in (project.get("optional-dependencies") or {}).items():
        for raw in items:
            parsed = _parse_pep508(raw)
            if not parsed:
                continue
            name, spec = parsed
            rows.append(
                _make_dep(
                    user_id, repository_name, ws, pep621_pm, name, spec,
                    rel_source, group_name,
                )
            )

    for group_name, items in (data.get("dependency-groups") or {}).items():
        for raw in items:
            parsed = _parse_pep508(raw) if isinstance(raw, str) else None
            if not parsed:
                continue
            name, spec = parsed
            rows.append(
                _make_dep(
                    user_id, repository_name, ws, "uv", name, spec,
                    rel_source, group_name,
                )
            )

    return rows


def _parse_requirements_txt(
    path: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    rows: List[RepositoryDependency] = []
    rel_source = _rel(path, ws)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                if line.startswith("git+") or line.startswith("http"):
                    continue
                parsed = _parse_pep508(line)
                if not parsed:
                    continue
                name, spec = parsed
                rows.append(
                    _make_dep(
                        user_id, repository_name, ws, "pip", name, spec,
                        rel_source, "runtime",
                    )
                )
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
    return rows


def _stringify_poetry_spec(spec) -> Optional[str]:
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        if "version" in spec:
            return str(spec["version"])
        if "git" in spec:
            return f"git+{spec['git']}"
        if "path" in spec:
            return f"path:{spec['path']}"
    return None


def _parse_pep508(raw: str) -> Optional[tuple]:
    """Best-effort PEP 508 parse — returns ``(name, spec)`` or None."""
    text = raw.split(";", 1)[0].strip()
    text = text.split(" #", 1)[0].strip()
    if not text:
        return None
    m = REQ_LINE.match(text)
    if not m:
        return None
    name = m.group("name")
    spec = (m.group("spec") or "").strip() or None
    return name, spec


# -- Node -----------------------------------------------------------------

def _parse_package_json(
    ws_dir: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    pkg = ws_dir / "package.json"
    if not pkg.exists():
        return []
    try:
        with open(pkg, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", pkg, exc)
        return []

    rel_source = _rel(pkg, ws)
    pm = ws.detected_package_manager or "npm"
    rows: List[RepositoryDependency] = []

    for group_field, group_name in (
        ("dependencies", "runtime"),
        ("devDependencies", "dev"),
        ("peerDependencies", "peer"),
        ("optionalDependencies", "optional"),
    ):
        for name, version in (data.get(group_field) or {}).items():
            rows.append(
                _make_dep(
                    user_id, repository_name, ws, pm, name, version,
                    rel_source, group_name,
                )
            )
    return rows


# -- Go --------------------------------------------------------------------

GO_REQUIRE_LINE = re.compile(r"^\s*([\w./~-]+)\s+([\w.+\-]+)")


def _parse_go_mod(
    ws_dir: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    path = ws_dir / "go.mod"
    if not path.exists():
        return []
    rel_source = _rel(path, ws)
    rows: List[RepositoryDependency] = []
    in_block = False
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("//"):
                    continue
                if line.startswith("require ("):
                    in_block = True
                    continue
                if in_block and line == ")":
                    in_block = False
                    continue
                if in_block:
                    m = GO_REQUIRE_LINE.match(raw)
                    if m:
                        rows.append(
                            _make_dep(
                                user_id, repository_name, ws, "go_modules",
                                m.group(1), m.group(2), rel_source, "runtime",
                            )
                        )
                elif line.startswith("require "):
                    rest = line[len("require "):].strip()
                    m = GO_REQUIRE_LINE.match(rest)
                    if m:
                        rows.append(
                            _make_dep(
                                user_id, repository_name, ws, "go_modules",
                                m.group(1), m.group(2), rel_source, "runtime",
                            )
                        )
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
    return rows


# -- Rust ------------------------------------------------------------------

def _parse_cargo_toml(
    ws_dir: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    path = ws_dir / "Cargo.toml"
    if not path.exists():
        return []
    try:
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return []

    rel_source = _rel(path, ws)
    rows: List[RepositoryDependency] = []
    for field, group in (
        ("dependencies", "runtime"),
        ("dev-dependencies", "dev"),
        ("build-dependencies", "build"),
    ):
        for name, spec in (data.get(field) or {}).items():
            version = spec if isinstance(spec, str) else (spec or {}).get("version")
            rows.append(
                _make_dep(
                    user_id, repository_name, ws, "cargo", name, version,
                    rel_source, group,
                )
            )
    return rows


# -- Helm ------------------------------------------------------------------

def _parse_chart_yaml(
    ws_dir: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    path = ws_dir / "Chart.yaml"
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not installed; skipping Chart.yaml parse: %s", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return []

    rel_source = _rel(path, ws)
    rows: List[RepositoryDependency] = []
    for dep in data.get("dependencies", []) or []:
        if not isinstance(dep, dict):
            continue
        name = dep.get("name")
        if not name:
            continue
        rows.append(
            _make_dep(
                user_id, repository_name, ws, "helm", name,
                dep.get("version"), rel_source, "runtime",
            )
        )
    return rows


# -- Chef ------------------------------------------------------------------

# Berksfile lines: ``cookbook 'name', '~> 1.2'`` (single or double quotes).
BERKSFILE_LINE = re.compile(
    r"""^\s*cookbook\s+["'](?P<name>[^"']+)["']\s*"""
    r"""(?:,\s*["'](?P<version>[^"']+)["'])?"""
)
# metadata.rb depends lines: ``depends 'name', '>= 1.0'``.
METADATA_DEPENDS = re.compile(
    r"""^\s*depends\s+["'](?P<name>[^"']+)["']\s*"""
    r"""(?:,\s*["'](?P<version>[^"']+)["'])?"""
)


def _parse_berksfile(
    ws_dir: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    path = ws_dir / "Berksfile"
    rel_source = _rel(path, ws)
    rows: List[RepositoryDependency] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = BERKSFILE_LINE.match(line)
                if not m:
                    continue
                rows.append(
                    _make_dep(
                        user_id, repository_name, ws, "chef", m.group("name"),
                        m.group("version"), rel_source, "runtime",
                    )
                )
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
    return rows


def _parse_chef_metadata(
    ws_dir: Path, ws: RepositoryWorkspace, user_id: str, repository_name: str
) -> List[RepositoryDependency]:
    path = ws_dir / "metadata.rb"
    rel_source = _rel(path, ws)
    rows: List[RepositoryDependency] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = METADATA_DEPENDS.match(line)
                if not m:
                    continue
                rows.append(
                    _make_dep(
                        user_id, repository_name, ws, "chef", m.group("name"),
                        m.group("version"), rel_source, "runtime",
                    )
                )
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
    return rows


# -- Helpers --------------------------------------------------------------

def _rel(path: Path, ws: RepositoryWorkspace) -> str:
    if ws.workspace_path == ".":
        return path.name
    return f"{ws.workspace_path}/{path.name}"


def _make_dep(
    user_id: str,
    repository_name: str,
    ws: RepositoryWorkspace,
    package_manager: str,
    name: str,
    version: Optional[str],
    source_file: str,
    dependency_group: str,
) -> RepositoryDependency:
    return RepositoryDependency(
        user_id=user_id,
        repository_name=repository_name,
        package_manager=package_manager,
        name=name,
        version_constraint=version,
        dependency_group=dependency_group,
        source_file=source_file,
        evidence=[{"kind": "manifest", "path": source_file}],
    )
