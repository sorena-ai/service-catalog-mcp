"""Pydantic filter shapes for the search service.

Two surfaces:
  - ``AgentSearchFilters``: agent-internal, accepts arbitrary extras (e.g.
    raw ``extraction`` filters for the generic collection).
  - ``PublicSearchFilters``: MCP-facing, ``extra="forbid"``. ``has_file``
    and ``workspace_manifest`` values are checked against a whitelist
    in ``service.IndexSearchService.public_search``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from sdk.vocabulary import Framework, Language, Platform

VersionOp = Literal["==", ">=", "<=", ">", "<", "~="]


class DependencyFilter(BaseModel):
    name: str
    version: Optional[str] = None
    op: VersionOp = "=="


class DockerImageFilter(BaseModel):
    name: str
    tag: Optional[str] = None


class GithubActionFilter(BaseModel):
    owner: str
    name: str
    version_ref: Optional[str] = None


# Patterns the public surface accepts for ``has_file``.
PUBLIC_HAS_FILE_WHITELIST = frozenset({
    "Dockerfile",
    "go.mod",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "Chart.yaml",
    "main.tf",
    "metadata.rb",
    "Berksfile",
    "docker-compose.yml",
    ".github/workflows/*.yml",
})

PUBLIC_WORKSPACE_MANIFEST_WHITELIST = frozenset({
    "package.json",
    "go.mod",
    "pyproject.toml",
    "Cargo.toml",
    "Chart.yaml",
    "main.tf",
    "metadata.rb",
})


class PublicSearchFilters(BaseModel):
    """MCP-facing strict filter shape. Unknown fields rejected."""

    model_config = ConfigDict(extra="forbid")

    language: Optional[Language] = Field(
        None, description="Primary language of the repository.", examples=["go"]
    )
    framework: Optional[Framework] = Field(
        None, description="Web or application framework used.", examples=["fastapi"]
    )
    platform: Optional[Platform] = Field(
        None, description="Deployment or infrastructure platform.", examples=["docker"]
    )
    dependency: Optional[DependencyFilter] = None
    docker_image: Optional[DockerImageFilter] = None
    github_action: Optional[GithubActionFilter] = None
    has_file: Optional[str] = Field(
        None,
        description="Whitelisted filename or path pattern (e.g. Dockerfile, go.mod, .github/workflows/*.yml).",
    )
    workspace_manifest: Optional[str] = Field(
        None,
        description="Whitelisted workspace manifest filename (package.json, go.mod, pyproject.toml, ...).",
    )


class AgentSearchFilters(BaseModel):
    """Agent-side filters. Allows ``extraction`` for raw access."""

    model_config = ConfigDict(extra="ignore")

    repository_names: Optional[List[str]] = None
    dependency: Optional[DependencyFilter] = None
    framework: Optional[str] = None
    language: Optional[str] = None
    platform: Optional[str] = None
    docker_image: Optional[DockerImageFilter] = None
    github_action: Optional[GithubActionFilter] = None
    has_file: Optional[str] = None
    workspace_manifest: Optional[str] = None
    extraction: Optional[Dict[str, Any]] = None
