"""File curator — pick files of interest and tag them with a role."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from ..db.files import RepositoryFile
from ._walker import walk_repo
from .languages import EXT_LANGUAGE

# Filenames that are themselves manifests, regardless of directory.
MANIFEST_FILENAMES = frozenset({
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "lerna.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "go.mod",
    "go.sum",
    "go.work",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "Chart.yaml",
    "Chart.lock",
    "Berksfile",
    "Berksfile.lock",
    "metadata.rb",
    "Policyfile.rb",
    "Policyfile.lock.json",
})

# Manifest patterns that need globbing.
MANIFEST_REGEXES = (
    re.compile(r"^requirements.*\.txt$"),
    re.compile(r"^.*\.gemspec$"),
)

# Dockerfile patterns.
DOCKERFILE_REGEXES = (
    re.compile(r"^Dockerfile.*$"),
    re.compile(r"^.*\.dockerfile$"),
)

DOCKER_COMPOSE_FILENAMES = frozenset({
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
})

# CI files.
CI_FILENAMES = frozenset({
    ".gitlab-ci.yml",
    ".travis.yml",
    "Jenkinsfile",
    "azure-pipelines.yml",
    "buildkite.yml",
    ".buildkite",
})

CI_PATH_PREFIXES = (
    ".github/workflows/",
    ".circleci/",
)

# Top-level entrypoint candidates by language.
ENTRYPOINT_REGEXES = (
    re.compile(r"^main\.py$"),
    re.compile(r"^app\.py$"),
    re.compile(r"^src/main\.rs$"),
    re.compile(r"^cmd/[^/]+/main\.go$"),
    re.compile(r"^main\.go$"),
    re.compile(r"^index\.(ts|tsx|js|jsx|mjs|cjs)$"),
    re.compile(r"^src/index\.(ts|tsx|js|jsx|mjs|cjs)$"),
    re.compile(r"^server\.(ts|js|py)$"),
    re.compile(r"^manage\.py$"),
)

# Top-level config files (TOML/YAML/INI/env).
CONFIG_REGEXES = (
    re.compile(r"^\.env(\..+)?$"),
    re.compile(r"^.+\.cfg$"),
    re.compile(r"^.+\.ini$"),
    re.compile(r"^tsconfig.*\.json$"),
    re.compile(r"^.eslintrc.*$"),
    re.compile(r"^.prettierrc.*$"),
    re.compile(r"^pre-commit-config\.yaml$"),
    re.compile(r"^\.pre-commit-config\.yaml$"),
)

# READMEs (case-insensitive).
README_REGEX = re.compile(r"^README(\..*)?$", re.IGNORECASE)


def scan_files(
    repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryFile]:
    rows: List[RepositoryFile] = []
    for rel, size in walk_repo(repo_dir):
        role = _classify(rel)
        if role is None:
            continue
        rows.append(
            RepositoryFile(
                user_id=user_id,
                repository_name=repository_name,
                path=rel,
                role=role,
                language=EXT_LANGUAGE.get(_ext(rel)),
                size_bytes=size,
                evidence=[{"kind": _evidence_kind(role), "path": rel}],
            )
        )
    return rows


def _classify(rel: str) -> Optional[str]:
    name = rel.rsplit("/", 1)[-1]
    is_top_level = "/" not in rel

    for prefix in CI_PATH_PREFIXES:
        if rel.startswith(prefix):
            return "ci"
    if name in CI_FILENAMES:
        return "ci"

    for rx in DOCKERFILE_REGEXES:
        if rx.match(name):
            return "dockerfile"
    if name in DOCKER_COMPOSE_FILENAMES:
        return "dockerfile"

    if name in MANIFEST_FILENAMES:
        return "manifest"
    for rx in MANIFEST_REGEXES:
        if rx.match(name):
            return "manifest"

    if is_top_level and README_REGEX.match(name):
        return "readme"

    for rx in ENTRYPOINT_REGEXES:
        if rx.match(rel):
            return "entrypoint"

    if is_top_level:
        for rx in CONFIG_REGEXES:
            if rx.match(name):
                return "config"

    return None


def _evidence_kind(role: str) -> str:
    if role == "manifest":
        return "manifest"
    if role == "dockerfile":
        return "dockerfile"
    if role == "ci":
        return "workflow"
    if role == "readme":
        return "readme"
    return "source"


def _ext(rel_path: str) -> str:
    idx = rel_path.rfind(".")
    if idx == -1:
        return ""
    return rel_path[idx:].lower()
