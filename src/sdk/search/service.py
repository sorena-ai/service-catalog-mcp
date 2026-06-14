"""IndexSearchService — single entry point for indexer queries.

Two paths:
  - ``search`` (agent): flexible filter, no rate limit, returns evidence.
  - ``public_search`` (MCP): whitelisted filter, hard caps, narrower
    return shape. Rate limits are applied at the route layer; this
    service enforces filter validity.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sdk.errors import InvalidRequestError
from sdk.search.models import (
    CodebaseGlossary,
    ContextHit,
    EvidenceItem,
    RepositoryMatch,
    SearchResult,
    SearchResultNL,
)

from ..indexer.db.codebase_contexts import CodebaseContext, CodebaseContextDB
from ..indexer.db.codebase_runs import CodebaseRunDB
from ..indexer.db.contexts import RepositoryContext, RepositoryContextDB
from ..indexer.db.dependencies import RepositoryDependencyDB
from ..indexer.db.edges import RepositoryEdgeDB
from ..indexer.db.extractions import RepositoryExtractionDB
from ..indexer.db.files import RepositoryFileDB
from ..indexer.db.languages import RepositoryLanguageDB
from ..indexer.db.tree import RepositoryTreeDB
from ..indexer.db.workspaces import RepositoryWorkspaceDB
from .filters import (
    AgentSearchFilters,
    PUBLIC_HAS_FILE_WHITELIST,
    PUBLIC_WORKSPACE_MANIFEST_WHITELIST,
    PublicSearchFilters,
)

logger = logging.getLogger(__name__)

PUBLIC_RESULT_CAP = 50
AGENT_RESULT_CAP = 200


class IndexSearchService:
    def __init__(self) -> None:
        self.lang_db = RepositoryLanguageDB()
        self.dep_db = RepositoryDependencyDB()
        self.ws_db = RepositoryWorkspaceDB()
        self.tree_db = RepositoryTreeDB()
        self.file_db = RepositoryFileDB()
        self.ext_db = RepositoryExtractionDB()
        self.ctx_db = RepositoryContextDB()
        self.edge_db = RepositoryEdgeDB()
        self.codebase_ctx_db = CodebaseContextDB()
        self.codebase_runs_db = CodebaseRunDB()

    # -- search ----------------------------------------------------------

    def search(
        self, user_id: str, filters: AgentSearchFilters, limit: int = 100
    ) -> dict:
        limit = min(limit, AGENT_RESULT_CAP)
        candidates, evidence = self._candidates_from_filters(user_id, filters)
        if candidates is None:
            return {
                "exact_matches": [],
                "near_matches": [],
                "context_hits": [],
                "not_found": [],
            }

        ordered = sorted(candidates)[:limit]
        return {
            "exact_matches": [
                {"repository_name": r, "evidence": evidence.get(r, [])}
                for r in ordered
            ],
            "near_matches": [],
            "context_hits": [],
            "not_found": [],
        }

    def public_search_with_nl(
        self,
        user_id: str,
        nl_query: str,
        limit: int = 20,
    ) -> SearchResultNL:
        """NL-driven public search.

        Resolves ``nl_query`` against codebase contexts, runs the
        resulting structured filter through ``public_search``, and
        augments with ``context_hits`` from text search over
        ``repository_contexts.content``.
        """
        from .nl_resolver import NLResolverError, resolve_nl_query

        try:
            filters, keywords = resolve_nl_query(user_id, nl_query)
        except NLResolverError as exc:
            raise InvalidRequestError(f"could not resolve nl_query: {exc}")

        result = self.public_search(user_id, filters, limit=limit)

        context_hits: list[ContextHit] = []
        if keywords:
            raw_hits = self.search_repo_contexts_text(
                user_id, " ".join(keywords), limit=limit
            )
            context_hits = [ContextHit(**h) for h in raw_hits[:limit]]

        return SearchResultNL(
            exact_matches=result.exact_matches,
            near_matches=result.near_matches,
            not_found=result.not_found,
            context_hits=context_hits,
            resolved_filters=filters.model_dump(exclude_none=True),
            resolver_keywords=keywords,
        )

    def public_search(
        self,
        user_id: str,
        filters: PublicSearchFilters,
        limit: int = 20,
    ) -> SearchResult:
        limit = min(limit, PUBLIC_RESULT_CAP)
        if filters.has_file and filters.has_file not in PUBLIC_HAS_FILE_WHITELIST:
            raise InvalidRequestError(f"has_file value not allowed: {filters.has_file}")
        if (
            filters.workspace_manifest
            and filters.workspace_manifest not in PUBLIC_WORKSPACE_MANIFEST_WHITELIST
        ):
            raise InvalidRequestError(
                f"workspace_manifest value not allowed: {filters.workspace_manifest}"
            )

        agent_filters = AgentSearchFilters(**filters.model_dump(exclude_none=True))
        raw = self.search(user_id, agent_filters, limit=limit)

        exact: list[RepositoryMatch] = []
        for match in raw["exact_matches"]:
            ev = match.get("evidence") or []
            stripped = [EvidenceItem(kind=e["kind"], path=e.get("path")) for e in ev[:5]]
            exact.append(RepositoryMatch(repository_name=match["repository_name"], evidence=stripped))

        return SearchResult(
            exact_matches=exact,
            near_matches=[RepositoryMatch(repository_name=m["repository_name"]) for m in raw.get("near_matches", [])],
            not_found=raw.get("not_found", []),
        )

    # -- per-repo readers -----------------------------------------------

    def get_repo_facts(self, user_id: str, repository_name: str) -> dict:
        tree = self.tree_db.get(user_id, repository_name)
        return {
            "repository_name": repository_name,
            "languages": [
                {"language": lang.language, "confidence": lang.confidence}
                for lang in self.lang_db.find_for_repository(user_id, repository_name)
            ],
            "workspaces": [
                {
                    "workspace_path": w.workspace_path,
                    "manifest_files": w.manifest_files,
                    "detected_language": w.detected_language,
                    "detected_package_manager": w.detected_package_manager,
                }
                for w in self.ws_db.find_for_repository(user_id, repository_name)
            ],
            "files": [
                {"path": f.path, "role": f.role, "language": f.language}
                for f in self.file_db.find_for_repository(user_id, repository_name)
            ],
            "tree_path_count": tree.file_count if tree else 0,
            "dependencies": [
                {
                    "package_manager": d.package_manager,
                    "name": d.name,
                    "version_constraint": d.version_constraint,
                    "dependency_group": d.dependency_group,
                    "source_file": d.source_file,
                }
                for d in self.dep_db.find_for_repository(user_id, repository_name)
            ],
            "extractions": _group_extractions(
                self.ext_db.find_for_repository(user_id, repository_name)
            ),
        }

    def get_repo_contexts(
        self,
        user_id: str,
        repository_name: str,
        types: Optional[List[str]] = None,
        workspace: Optional[str] = None,
    ) -> List[dict]:
        rows = self.ctx_db.find_for_repository(user_id, repository_name, types, workspace)
        return [_context_to_dict(r) for r in rows]

    def search_repo_contexts_text(
        self,
        user_id: str,
        query_text: str,
        context_types: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[dict]:
        rows = self.ctx_db.text_search(user_id, query_text, context_types, limit)
        return [
            {
                "repository_name": r.repository_name,
                "context_type": r.context_type,
                "snippet": (r.content or "")[:500],
                "tags": r.tags,
                "workspace_path": r.workspace_path,
            }
            for r in rows
        ]

    def get_repo_tree(self, user_id: str, repository_name: str) -> dict:
        tree = self.tree_db.get(user_id, repository_name)
        if not tree:
            return {"repository_name": repository_name, "paths": [], "file_count": 0}
        return {
            "repository_name": repository_name,
            "paths": tree.paths,
            "file_count": tree.file_count,
            "depth_max": tree.depth_max,
            "fingerprint": tree.fingerprint,
        }

    # -- codebase --------------------------------------------------------

    def get_codebase_glossary(self, user_id: str) -> CodebaseGlossary:
        rows = self.codebase_ctx_db.find_for_user(
            user_id, context_types=["codebase_terminology", "query_refinement_hints"]
        )
        by_type = {r.context_type: r.content for r in rows}
        return CodebaseGlossary(
            terminology=by_type.get("codebase_terminology", ""),
            query_hints=by_type.get("query_refinement_hints", ""),
            has_glossary=bool(by_type),
        )

    def get_codebase_contexts(
        self, user_id: str, types: Optional[List[str]] = None
    ) -> List[dict]:
        return [
            _codebase_context_to_dict(c)
            for c in self.codebase_ctx_db.find_for_user(user_id, types)
        ]

    def codebase_status(self, user_id: str) -> dict:
        latest = self.codebase_runs_db.get_latest(user_id)
        if not latest:
            return {"has_run": False, "latest": None}
        return {
            "has_run": True,
            "latest": {
                "id": str(latest._id) if latest._id else None,
                "status": latest.status,
                "trigger": latest.trigger,
                "input_repository_names": latest.input_repository_names,
                "started_at": latest.started_at.isoformat() if latest.started_at else None,
                "completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
                "cost_usd": latest.cost_usd,
                "error_message": latest.error_message,
            },
        }

    # -- impact ----------------------------------------------------------

    def dependency_impact(self, user_id: str, target: str) -> dict:
        edges = self.edge_db.find_incoming(user_id, target)
        dependents = sorted({e.from_repository for e in edges})
        return {
            "target": target,
            "dependents": dependents,
            "edge_types": sorted({e.edge_type for e in edges}),
        }

    # -- candidate filtering ---------------------------------------------

    def _candidates_from_filters(
        self, user_id: str, filters: AgentSearchFilters
    ) -> tuple[Optional[set[str]], Dict[str, list]]:
        candidates: Optional[set[str]] = None
        evidence_by_repo: Dict[str, list] = defaultdict(list)

        def narrow(repos: list[str], evidence_kind: str, evidence_value: Any) -> None:
            nonlocal candidates
            repo_set = set(repos)
            candidates = repo_set if candidates is None else candidates & repo_set
            for r in repo_set:
                evidence_by_repo[r].append({"kind": evidence_kind, "match": evidence_value})

        if filters.repository_names:
            narrow(filters.repository_names, "repository_names", filters.repository_names)

        if filters.dependency:
            version = (
                filters.dependency.version
                if filters.dependency.op == "==" and filters.dependency.version
                else None
            )
            repos = self.dep_db.find_repos_by_dependency(
                user_id, filters.dependency.name.lower(), version
            )
            narrow(repos, "dependency", filters.dependency.model_dump())

        if filters.language:
            repos = self.lang_db.find_repos_by_language(user_id, filters.language)
            narrow(repos, "language", filters.language)

        if filters.framework:
            repos = list(
                {
                    e.repository_name
                    for e in self.ext_db.find(
                        user_id, "framework", {"framework": filters.framework}
                    )
                }
            )
            narrow(repos, "framework", filters.framework)

        if filters.platform:
            repos = list(
                {
                    e.repository_name
                    for e in self.ext_db.find(
                        user_id, "platform", {"platform": filters.platform}
                    )
                }
            )
            narrow(repos, "platform", filters.platform)

        if filters.docker_image:
            data = {"image_name": filters.docker_image.name}
            if filters.docker_image.tag:
                data["tag"] = filters.docker_image.tag
            repos = list(
                {
                    e.repository_name
                    for e in self.ext_db.find(user_id, "docker_image", data)
                }
            )
            narrow(repos, "docker_image", filters.docker_image.model_dump())

        if filters.github_action:
            data = {
                "action_owner": filters.github_action.owner,
                "action_name": filters.github_action.name,
            }
            if filters.github_action.version_ref:
                data["version_ref"] = filters.github_action.version_ref
            repos = list(
                {
                    e.repository_name
                    for e in self.ext_db.find(user_id, "github_action", data)
                }
            )
            narrow(repos, "github_action", filters.github_action.model_dump())

        if filters.has_file:
            repos = self.tree_db.find_repos_with_path_pattern(user_id, filters.has_file)
            narrow(repos, "has_file", filters.has_file)

        if filters.workspace_manifest:
            repos = self.ws_db.find_repos_with_manifest(user_id, filters.workspace_manifest)
            narrow(repos, "workspace_manifest", filters.workspace_manifest)

        if filters.extraction:
            etype = (filters.extraction or {}).get("extraction_type")
            data = (filters.extraction or {}).get("data") or {}
            if etype:
                repos = list(
                    {
                        e.repository_name
                        for e in self.ext_db.find(user_id, etype, data)
                    }
                )
                narrow(repos, "extraction", {"extraction_type": etype, **data})

        return candidates, evidence_by_repo


# -- helpers ---------------------------------------------------------------

def _group_extractions(rows: list) -> Dict[str, list]:
    grouped: Dict[str, list] = defaultdict(list)
    for r in rows:
        grouped[r.extraction_type].append(r.data)
    return dict(grouped)


def _context_to_dict(c: RepositoryContext) -> dict:
    return {
        "context_type": c.context_type,
        "content": c.content,
        "workspace_path": c.workspace_path,
        "tags": c.tags,
        "paths": c.paths,
        "symbols": c.symbols,
    }


def _codebase_context_to_dict(c: CodebaseContext) -> dict:
    return {
        "context_type": c.context_type,
        "content": c.content,
        "tags": c.tags,
        "referenced_repositories": c.referenced_repositories,
    }


__all__ = ["IndexSearchService", "PUBLIC_RESULT_CAP", "AGENT_RESULT_CAP"]
