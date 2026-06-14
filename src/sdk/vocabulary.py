"""Shared extraction vocabulary for the indexer.

Embedded into codebase pass and repository pass prompts and used by scanners to keep
extracted values consistent across the codebase.

Scalar-filterable categories (Language, Framework, Platform, Runtime,
PackageManager) are defined as Literal types so mcp-server can couple
Pydantic field types directly to the vocabulary without duplicating strings.
"""

from typing import Literal

# ---------------------------------------------------------------------------
# Scalar-filterable categories — Literal first, list derived
# ---------------------------------------------------------------------------

Language = Literal[
    "python",
    "go",
    "typescript",
    "javascript",
    "rust",
    "java",
    "kotlin",
    "ruby",
    "csharp",
    "php",
    "shell",
]
LANGUAGES: list[str] = list(Language.__args__)

Framework = Literal[
    "fastapi",
    "django",
    "flask",
    "express",
    "nestjs",
    "react",
    "nextjs",
    "vue",
    "spring_boot",
    "rails",
    "gin",
    "chi",
    "echo",
    "fiber",
    "laravel",
]
FRAMEWORKS: list[str] = list(Framework.__args__)

Platform = Literal[
    "docker",
    "docker_swarm",
    "kubernetes",
    "helm",
    "chef",
    "terraform",
    "aws",
    "gcp",
    "azure",
    "github_actions",
    "argocd",
]
PLATFORMS: list[str] = list(Platform.__args__)

Runtime = Literal[
    "node",
    "python",
    "go",
    "jvm",
    "ruby",
    "dotnet",
    "php",
]
RUNTIMES: list[str] = list(Runtime.__args__)

PackageManager = Literal[
    "npm",
    "yarn",
    "pnpm",
    "pip",
    "poetry",
    "uv",
    "go_modules",
    "cargo",
    "maven",
    "gradle",
    "bundler",
    "composer",
    "helm",
    "chef",
]
PACKAGE_MANAGERS: list[str] = list(PackageManager.__args__)

# ---------------------------------------------------------------------------
# Plain lists — no Literal needed (not used as Pydantic field types)
# ---------------------------------------------------------------------------

REPO_CLASSES = [
    "service",
    "library",
    "cli",
    "infra",
    "monorepo",
    "dashboard",
    "docs",
    "unknown",
]

DEPENDENCY_GROUPS = [
    "runtime",
    "dev",
    "peer",
    "optional",
    "test",
    "build",
]

REPO_CONTEXT_TYPES = [
    "repo_summary",
    "architecture",
    "dependency_notes",
    "docker_notes",
    "ci_notes",
    "deploy_notes",
    "testing_notes",
    "service_api",
    "change_planning_notes",
]

CODEBASE_CONTEXT_TYPES = [
    "codebase_summary",
    "codebase_architecture",
    "cross_repo_relationships",
    "tech_stack_overview",
    "codebase_terminology",
    "query_refinement_hints",
]

EDGE_TYPES = [
    "depends_on",
    "uses_package",
    "uses_action",
    "uses_image",
    "calls_service",
    "shares_framework",
    "shares_runtime",
    "owns_artifact",
]

EVIDENCE_KINDS = [
    "manifest",
    "lockfile",
    "dockerfile",
    "workflow",
    "source",
    "readme",
    "llm_inferred",
]

FILE_ROLES = [
    "manifest",
    "dockerfile",
    "ci",
    "route",
    "entrypoint",
    "config",
    "readme",
    "important_source",
]

EXTRACTION_TYPES = [
    "docker_image",
    "compose_service",
    "swarm_stack",
    "github_action",
    "ci_workflow",
    "kubernetes_object",
    "helm_chart",
    "terraform_module",
    "chef_cookbook",
    "build_target",
    "framework",
    "platform",
    "internal_api",
    "symbol",
    "pattern",
]
