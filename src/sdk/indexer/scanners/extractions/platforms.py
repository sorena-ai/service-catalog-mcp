"""Platform extractions derived from file presence.

Each detection emits a single ``platform`` extraction with the canonical
platform name and the path that triggered it. Cloud platforms (aws, gcp,
azure) are only inferred from infrastructure file patterns — we do not
guess from import statements.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from ...db.extractions import RepositoryExtraction
from ...db.tree import RepositoryTree

EXTRACTION_TO_PLATFORM = {
    "kubernetes_object": ("kubernetes", "manifest"),
    "helm_chart": ("helm", "manifest"),
    "swarm_stack": ("docker_swarm", "manifest"),
    "terraform_module": ("terraform", "manifest"),
    "chef_cookbook": ("chef", "manifest"),
    "github_action": ("github_actions", "workflow"),
}

# Each rule: (platform, evidence_kind, predicate)
# predicate operates on a relative path string.
def _predicate(name: str):
    return lambda p: p.endswith("/" + name) or p == name


def _suffix(suffix: str):
    return lambda p: p.endswith(suffix)


def _prefix(prefix: str):
    return lambda p: p.startswith(prefix)


_RULES = [
    ("docker", "dockerfile", lambda p: p == "Dockerfile" or p.endswith("/Dockerfile") or p.endswith(".dockerfile")),
    ("docker", "manifest", lambda p: p in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"} or p.endswith("/docker-compose.yml") or p.endswith("/docker-compose.yaml") or p.endswith("/compose.yml") or p.endswith("/compose.yaml")),
    ("kubernetes", "manifest", lambda p: p == "kustomization.yaml" or p.endswith("/kustomization.yaml") or p == "kustomization.yml" or p.endswith("/kustomization.yml")),
    ("helm", "manifest", _predicate("Chart.yaml")),
    ("terraform", "manifest", _suffix(".tf")),
    ("chef", "manifest", _predicate("metadata.rb")),
    ("chef", "manifest", _predicate("Berksfile")),
    ("github_actions", "workflow", _prefix(".github/workflows/")),
    ("argocd", "manifest", lambda p: "/argocd/" in p or p.startswith("argocd/") or p.endswith("/argocd-app.yaml")),
]


def scan_platforms(
    tree_paths: Iterable[str],
    user_id: str,
    repository_name: str,
    extractions: Optional[Iterable[RepositoryExtraction]] = None,
) -> List[RepositoryExtraction]:
    """Detect platforms from a repository's path list and optionally the
    extractions other scanners have already produced.

    File-presence rules cover the obvious cases (``Dockerfile`` → docker,
    ``*.tf`` → terraform). Some platforms (kubernetes, docker_swarm) need
    content inspection that other extractors already do, so we lift their
    output into ``platform`` rows here.
    """
    rows: List[RepositoryExtraction] = []
    seen: set[str] = set()
    paths = list(tree_paths)
    for platform, kind, predicate in _RULES:
        if platform in seen:
            continue
        evidence_path = next((p for p in paths if predicate(p)), None)
        if not evidence_path:
            continue
        seen.add(platform)
        rows.append(
            RepositoryExtraction(
                user_id=user_id,
                repository_name=repository_name,
                extraction_type="platform",
                data={
                    "platform": platform,
                    "evidence_path": evidence_path,
                },
                evidence=[{"kind": kind, "path": evidence_path}],
            )
        )

    if extractions:
        for ext in extractions:
            mapping = EXTRACTION_TO_PLATFORM.get(ext.extraction_type)
            if not mapping:
                continue
            platform, kind = mapping
            if platform in seen:
                continue
            seen.add(platform)
            evidence_path = (ext.evidence[0].get("path") if ext.evidence else None) or ""
            rows.append(
                RepositoryExtraction(
                    user_id=user_id,
                    repository_name=repository_name,
                    extraction_type="platform",
                    data={
                        "platform": platform,
                        "evidence_path": evidence_path,
                    },
                    evidence=[{"kind": kind, "path": evidence_path}],
                )
            )
    return rows


def scan_platforms_from_tree(
    tree: RepositoryTree,
    extractions: Optional[Iterable[RepositoryExtraction]] = None,
) -> List[RepositoryExtraction]:
    return scan_platforms(tree.paths, tree.user_id, tree.repository_name, extractions)


__all__ = ["scan_platforms", "scan_platforms_from_tree"]
