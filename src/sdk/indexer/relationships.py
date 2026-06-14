"""Build ``repository_edges`` from deterministic facts.

Run after the repository pass deterministic scanners have written facts for every repo
in the event so cross-repo edges resolve correctly. The output is a flat
list of ``RepositoryEdge`` rows; ``persist_edges`` groups them by source
repo and replaces previous edges atomically per repo.

Edge types produced:
  - ``uses_image``   — repo → ``image_name[:tag]`` (one per unique image ref)
  - ``uses_action``  — repo → ``owner/name`` (one per unique GHA reference)
  - ``uses_package`` — repo → ``package_manager:name_normalized``
  - ``depends_on``   — repo → repo, when a dep maps to another indexed repo

Edges intentionally NOT built here (derivable at query time or LLM
territory): ``shares_framework``, ``shares_runtime``, ``owns_artifact``,
``calls_service``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable, List, Optional, Set

from .db.dependencies import RepositoryDependencyDB
from .db.edges import RepositoryEdge, RepositoryEdgeDB
from .db.extractions import RepositoryExtractionDB

logger = logging.getLogger(__name__)


def build_edges(user_id: str, repository_names: Iterable[str]) -> List[RepositoryEdge]:
    repo_list = list(repository_names)
    repo_set: Set[str] = set(repo_list)

    edges: List[RepositoryEdge] = []
    edges.extend(_uses_image_edges(user_id, repo_list))
    edges.extend(_uses_action_edges(user_id, repo_list))
    edges.extend(_uses_package_edges(user_id, repo_list))
    edges.extend(_cross_repo_depends_on(user_id, repo_list, repo_set))
    return edges


def persist_edges(user_id: str, repository_names: Iterable[str], edges: List[RepositoryEdge]) -> None:
    """Persist edges, replacing all outgoing edges for each named repo.

    ``repository_names`` is the set of repos that were re-indexed in this
    event. We replace edges only for those — edges from un-touched repos
    are left intact.
    """
    db = RepositoryEdgeDB()
    grouped: dict[str, List[RepositoryEdge]] = defaultdict(list)
    for e in edges:
        grouped[e.from_repository].append(e)

    for repo in repository_names:
        db.replace_from_repository(user_id, repo, grouped.get(repo, []))


# -- per edge-type ---------------------------------------------------------

def _uses_image_edges(user_id: str, repos: List[str]) -> List[RepositoryEdge]:
    ext_db = RepositoryExtractionDB()
    edges: List[RepositoryEdge] = []
    for repo in repos:
        seen: Set[str] = set()
        for ext in ext_db.find_for_repository(user_id, repo, "docker_image"):
            ref = ext.data.get("ref") or _join_ref(
                ext.data.get("image_name"), ext.data.get("tag")
            )
            if not ref or ref in seen:
                continue
            seen.add(ref)
            edges.append(
                RepositoryEdge(
                    user_id=user_id,
                    from_repository=repo,
                    to_repository_or_artifact=ref,
                    edge_type="uses_image",
                    source="deterministic",
                    confidence=1.0,
                    evidence=ext.evidence,
                )
            )
    return edges


def _uses_action_edges(user_id: str, repos: List[str]) -> List[RepositoryEdge]:
    ext_db = RepositoryExtractionDB()
    edges: List[RepositoryEdge] = []
    for repo in repos:
        seen: Set[str] = set()
        for ext in ext_db.find_for_repository(user_id, repo, "github_action"):
            owner = ext.data.get("action_owner")
            name = ext.data.get("action_name")
            if not name:
                continue
            ref = f"{owner}/{name}" if owner else name
            if ref in seen:
                continue
            seen.add(ref)
            edges.append(
                RepositoryEdge(
                    user_id=user_id,
                    from_repository=repo,
                    to_repository_or_artifact=ref,
                    edge_type="uses_action",
                    source="deterministic",
                    confidence=1.0,
                    evidence=ext.evidence,
                )
            )
    return edges


def _uses_package_edges(user_id: str, repos: List[str]) -> List[RepositoryEdge]:
    dep_db = RepositoryDependencyDB()
    edges: List[RepositoryEdge] = []
    for repo in repos:
        seen: Set[str] = set()
        for dep in dep_db.find_for_repository(user_id, repo):
            artifact = f"{dep.package_manager}:{dep.name_normalized}"
            if artifact in seen:
                continue
            seen.add(artifact)
            edges.append(
                RepositoryEdge(
                    user_id=user_id,
                    from_repository=repo,
                    to_repository_or_artifact=artifact,
                    edge_type="uses_package",
                    source="deterministic",
                    confidence=1.0,
                    evidence=dep.evidence,
                )
            )
    return edges


def _cross_repo_depends_on(
    user_id: str, repos: List[str], repo_set: Set[str]
) -> List[RepositoryEdge]:
    """Cross-repo edges when one repo's dep maps to another repo's canonical name.

    Currently handled mappings:
      - ``go_modules``: ``github.com/{owner}/{name}`` → ``{owner}/{name}``
      - any PM: exact match of dep ``name`` against a repo name

    Other PMs (npm scoped packages, Java group:artifact, etc.) require
    user-specific naming conventions; we don't guess.
    """
    if not repo_set:
        return []
    dep_db = RepositoryDependencyDB()
    edges: List[RepositoryEdge] = []
    for repo in repos:
        seen: Set[str] = set()
        for dep in dep_db.find_for_repository(user_id, repo):
            target = _resolve_internal_repo(dep, repo_set)
            if not target or target == repo:
                continue
            key = f"{target}|{dep.package_manager}"
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                RepositoryEdge(
                    user_id=user_id,
                    from_repository=repo,
                    to_repository_or_artifact=target,
                    edge_type="depends_on",
                    source="deterministic",
                    confidence=0.9,
                    evidence=dep.evidence,
                )
            )
    return edges


def _resolve_internal_repo(dep, repo_set: Set[str]) -> Optional[str]:
    name = dep.name
    if dep.package_manager == "go_modules" and name.startswith("github.com/"):
        candidate = name[len("github.com/") :]
        parts = candidate.split("/")
        if len(parts) >= 2:
            owner_name = "/".join(parts[:2])
            if owner_name in repo_set:
                return owner_name
    if name in repo_set:
        return name
    return None


def _join_ref(image_name: Optional[str], tag: Optional[str]) -> Optional[str]:
    if not image_name:
        return None
    return f"{image_name}:{tag}" if tag else image_name


__all__ = ["build_edges", "persist_edges"]
