"""TinyDB-backed storage implementations for local mode.

Each collection's store interface is implemented natively with TinyDB.
Only the collections used by the local flow are fully implemented; others
raise NotImplementedError.

Full-text search is approximated with case-insensitive substring matching
ranked by match count.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage


logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("TINYDB_PATH", "/data/service-catalog/db.json")


def _get_db() -> TinyDB:
    """Open (or create) the TinyDB file, creating parent dirs if needed."""
    path = Path(DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(str(path), storage=JSONStorage)


def _now() -> datetime:
    return datetime.utcnow()


def _ts(obj: Any) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


# ---------------------------------------------------------------------------
# RepositoryFile store
# ---------------------------------------------------------------------------


class TinyRepositoryFileStore:
    def __init__(self):
        self._table = _get_db().table("repository_files")

    def replace_for_repository(self, scope: str, repository_name: str, files: list) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        if files:
            self._table.insert_multiple(
                {**f.to_dict(), "_scope": scope} for f in files
            )

    def find_for_repository(
        self,
        scope: str,
        repository_name: str,
        role: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> list:
        from sdk.indexer.db.files import RepositoryFile

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        results = [RepositoryFile.from_dict(d) for d in docs]
        if role is not None:
            results = [r for r in results if r.role == role]
        if workspace_path is not None:
            results = [r for r in results if r.workspace_path == workspace_path]
        return results

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed)

    def upsert(self, doc) -> None:
        Q = Query()
        doc.updated_at = _now()
        self._table.upsert(
            {**doc.to_dict(), "_scope": doc.user_id},
            (Q.user_id == doc.user_id)
            & (Q.repository_name == doc.repository_name)
            & (Q.path == doc.path),
        )


# ---------------------------------------------------------------------------
# RepositoryTree store
# ---------------------------------------------------------------------------


class TinyRepositoryTreeStore:
    def __init__(self):
        self._table = _get_db().table("repository_trees")

    def upsert(self, tree) -> None:
        Q = Query()
        tree.updated_at = _now()
        self._table.upsert(
            {**tree.to_dict(), "_scope": tree.user_id},
            (Q.user_id == tree.user_id)
            & (Q.repository_name == tree.repository_name),
        )

    def get(self, scope: str, repository_name: str) -> Optional[Any]:
        from sdk.indexer.db.tree import RepositoryTree

        Q = Query()
        doc = self._table.get(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return RepositoryTree.from_dict(doc) if doc else None

    def find_repos_with_path_pattern(self, scope: str, pattern: str) -> list[str]:
        from sdk.indexer.db.tree import RepositoryTree

        Q = Query()
        regex = re.compile(pattern)
        docs = self._table.search(Q.user_id == scope)
        matches = []
        for d in docs:
            tree = RepositoryTree.from_dict(d)
            if any(regex.search(p) for p in tree.paths):
                matches.append(tree.repository_name)
        return matches

    def delete(self, scope: str, repository_name: str) -> bool:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed) > 0


# ---------------------------------------------------------------------------
# RepositoryLanguage store
# ---------------------------------------------------------------------------


class TinyRepositoryLanguageStore:
    def __init__(self):
        self._table = _get_db().table("repository_languages")

    def replace_for_repository(self, scope: str, repository_name: str, languages: list) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        if languages:
            self._table.insert_multiple(
                {**lang.to_dict(), "_scope": scope} for lang in languages
            )

    def find_for_repository(self, scope: str, repository_name: str) -> list:
        from sdk.indexer.db.languages import RepositoryLanguage

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return [RepositoryLanguage.from_dict(d) for d in docs]

    def find_repos_by_language(self, scope: str, language: str) -> list[str]:
        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.language == language)
        )
        return list({d.get("repository_name", "") for d in docs})

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed)


# ---------------------------------------------------------------------------
# RepositoryDependency store
# ---------------------------------------------------------------------------


class TinyRepositoryDependencyStore:
    def __init__(self):
        self._table = _get_db().table("repository_dependencies")

    def replace_for_repository(self, scope: str, repository_name: str, deps: list) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        if deps:
            self._table.insert_multiple(
                {**d.to_dict(), "_scope": scope} for d in deps
            )

    def find_for_repository(self, scope: str, repository_name: str) -> list:
        from sdk.indexer.db.dependencies import RepositoryDependency

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return [RepositoryDependency.from_dict(d) for d in docs]

    def find_repos_by_dependency(
        self,
        scope: str,
        name_normalized: str,
        version_resolved: Optional[str] = None,
    ) -> list[str]:
        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.name_normalized == name_normalized)
        )
        if version_resolved is not None:
            docs = [d for d in docs if d.get("version_resolved") == version_resolved]
        return list({d.get("repository_name", "") for d in docs})

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed)


# ---------------------------------------------------------------------------
# RepositoryContext store — supports the main $text search
# ---------------------------------------------------------------------------


class TinyRepositoryContextStore:
    def __init__(self):
        self._table = _get_db().table("repository_contexts")

    def replace_for_repository(self, scope: str, repository_name: str, contexts: list) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        if contexts:
            self._table.insert_multiple(
                {**c.to_dict(), "_scope": scope} for c in contexts
            )

    def find_for_repository(self, scope: str, repository_name: str) -> list:
        from sdk.indexer.db.contexts import RepositoryContext

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return [RepositoryContext.from_dict(d) for d in docs]

    def search_text(self, scope: str, query_text: str) -> list:
        """Approximate full-text search via case-insensitive substring matching,
        ranked by total match count across all text fields.
        """
        from sdk.indexer.db.contexts import RepositoryContext

        Q = Query()
        docs = self._table.search(Q.user_id == scope)
        query_lower = query_text.lower()
        scored = []
        for d in docs:
            ctx = RepositoryContext.from_dict(d)
            text_fields = [
                ctx.context_type or "",
                ctx.content or "",
                ctx.summary or "",
            ]
            score = sum(tf.lower().count(query_lower) for tf in text_fields if tf)
            if score > 0:
                scored.append((score, ctx))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed)


# ---------------------------------------------------------------------------
# CodebaseContext store — supports $text search
# ---------------------------------------------------------------------------


class TinyCodebaseContextStore:
    def __init__(self):
        self._table = _get_db().table("codebase_contexts")

    def find_for_user(self, scope: str) -> list:
        from sdk.indexer.db.codebase_contexts import CodebaseContext

        Q = Query()
        docs = self._table.search(Q.user_id == scope)
        return [CodebaseContext.from_dict(d) for d in docs]

    def replace_for_user(self, scope: str, contexts: list) -> None:
        Q = Query()
        self._table.remove(Q.user_id == scope)
        if contexts:
            self._table.insert_multiple(
                {**c.to_dict(), "_scope": scope} for c in contexts
            )

    def search_text(self, scope: str, query_text: str) -> list:
        """Approximate full-text search via substring matching ranked by count."""
        from sdk.indexer.db.codebase_contexts import CodebaseContext

        Q = Query()
        docs = self._table.search(Q.user_id == scope)
        query_lower = query_text.lower()
        scored = []
        for d in docs:
            ctx = CodebaseContext.from_dict(d)
            text_fields = [
                ctx.context_type or "",
                ctx.content or "",
                ctx.summary or "",
            ]
            score = sum(tf.lower().count(query_lower) for tf in text_fields if tf)
            if score > 0:
                scored.append((score, ctx))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def delete_for_user(self, scope: str) -> int:
        Q = Query()
        removed = self._table.remove(Q.user_id == scope)
        return len(removed)


# ---------------------------------------------------------------------------
# UserRepository (repo registry) — critical for local mode
# ---------------------------------------------------------------------------


class TinyUserRepositoryStore:
    _table_name = "user_repositories"

    def __init__(self):
        self._table = _get_db().table(self._table_name)

    def add_user_repository(self, scope: str, repo_name: str, action: str) -> dict:
        from datetime import datetime

        Q = Query()
        now = datetime.utcnow()
        doc = {
            "user_id": scope,
            "repository_name": repo_name,
            "action": action,
            "is_indexed": False,
            "indexing_status": "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        existing = self._table.get(
            (Q.user_id == scope) & (Q.repository_name == repo_name)
        )
        if existing:
            return existing
        self._table.insert(doc)
        return doc

    def find_user_repository(self, scope: str, repository_name: str):
        from sdk.storage.db.mongo.repositories import UserRepository

        Q = Query()
        doc = self._table.get(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return UserRepository.from_dict(doc) if doc else None

    def find_user_repositories(self, scope: str) -> list:
        from sdk.storage.db.mongo.repositories import UserRepository

        Q = Query()
        docs = self._table.search(Q.user_id == scope)
        return [UserRepository.from_dict(d) for d in docs]

    def find_user_indexed_repositories(self, scope: str) -> list:
        from sdk.storage.db.mongo.repositories import UserRepository

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & Q.is_indexed
        )
        return [UserRepository.from_dict(d) for d in docs]

    def update_indexed_status(
        self, scope: str, repository_name: str, is_indexed: bool, indexing_status: str = "indexed"
    ) -> bool:
        from datetime import datetime

        Q = Query()
        result = self._table.update(
            {
                "is_indexed": is_indexed,
                "indexing_status": indexing_status,
                "updated_at": datetime.utcnow().isoformat(),
            },
            (Q.user_id == scope) & (Q.repository_name == repository_name),
        )
        return len(result) > 0

    def remove_user_repository(self, scope: str, repository_name: str) -> bool:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed) > 0

    def count_user_repositories(self, scope: str) -> int:
        Q = Query()
        return self._table.count(Q.user_id == scope)


# ---------------------------------------------------------------------------
# RepositoryWorkspace store
# ---------------------------------------------------------------------------


class TinyRepositoryWorkspaceStore:
    def __init__(self):
        self._table = _get_db().table("repository_workspaces")

    def replace_for_repository(self, scope: str, repository_name: str, workspaces: list) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        if workspaces:
            self._table.insert_multiple(
                {**w.to_dict(), "_scope": scope} for w in workspaces
            )

    def find_for_repository(self, scope: str, repository_name: str) -> list:
        from sdk.indexer.db.workspaces import RepositoryWorkspace

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return [RepositoryWorkspace.from_dict(d) for d in docs]

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed)


# ---------------------------------------------------------------------------
# RepositoryExtraction store
# ---------------------------------------------------------------------------


class TinyRepositoryExtractionStore:
    def __init__(self):
        self._table = _get_db().table("repository_extractions")

    def replace_for_repository_type(
        self, scope: str, repository_name: str, extraction_type: str, rows: list
    ) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope)
            & (Q.repository_name == repository_name)
            & (Q.extraction_type == extraction_type)
        )
        if rows:
            self._table.insert_multiple(
                {**r.to_dict(), "_scope": scope} for r in rows
            )

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.repository_name == repository_name)
        )
        return len(removed)

    def find_for_repository(
        self,
        scope: str,
        repository_name: str,
        extraction_type: Optional[str] = None,
    ) -> list:
        from sdk.indexer.db.extractions import RepositoryExtraction

        Q = Query()
        condition = (Q.user_id == scope) & (Q.repository_name == repository_name)
        if extraction_type:
            condition &= Q.extraction_type == extraction_type
        docs = self._table.search(condition)
        return [RepositoryExtraction.from_dict(d) for d in docs]


# ---------------------------------------------------------------------------
# RepositoryEdge store
# ---------------------------------------------------------------------------


class TinyRepositoryEdgeStore:
    def __init__(self):
        self._table = _get_db().table("repository_edges")

    def replace_for_repository(self, scope: str, repository_name: str, edges: list) -> None:
        Q = Query()
        self._table.remove(
            (Q.user_id == scope) & (Q.from_repository == repository_name)
        )
        if edges:
            self._table.insert_multiple(
                {**e.to_dict(), "_scope": scope} for e in edges
            )

    def find_for_repository(self, scope: str, repository_name: str) -> list:
        from sdk.indexer.db.edges import RepositoryEdge

        Q = Query()
        docs = self._table.search(
            (Q.user_id == scope) & (Q.from_repository == repository_name)
        )
        return [RepositoryEdge.from_dict(d) for d in docs]

    def delete_for_repository(self, scope: str, repository_name: str) -> int:
        Q = Query()
        removed = self._table.remove(
            (Q.user_id == scope) & (Q.from_repository == repository_name)
        )
        return len(removed)


# ---------------------------------------------------------------------------
# CodebaseRun store
# ---------------------------------------------------------------------------


class TinyCodebaseRunStore:
    def __init__(self):
        self._table = _get_db().table("codebase_runs")

    def insert(self, run) -> str:
        doc = {**run.to_dict(), "_scope": run.user_id}
        self._table.insert(doc)
        return str(doc.get("_id", ""))

    def update(self, run_id: str, fields: dict) -> None:
        Q = Query()
        self._table.update(fields, Q._id == run_id)

    def latest_for_user(self, scope: str):
        from sdk.indexer.db.codebase_runs import CodebaseRun

        Q = Query()
        docs = sorted(
            self._table.search(Q.user_id == scope),
            key=lambda d: d.get("created_at", ""),
            reverse=True,
        )
        return CodebaseRun.from_dict(docs[0]) if docs else None


# ---------------------------------------------------------------------------
# IndexEventRun store
# ---------------------------------------------------------------------------


class TinyIndexEventRunStore:
    def __init__(self):
        self._table = _get_db().table("indexing_event_runs")

    def insert(self, run) -> str:
        doc = {**run.to_dict(), "_scope": run.user_id}
        self._table.insert(doc)
        return str(doc.get("_id", ""))

    def update(self, run_id: str, fields: dict) -> None:
        Q = Query()
        self._table.update(fields, Q._id == run_id)


# ---------------------------------------------------------------------------
# Stubbed stores
# ---------------------------------------------------------------------------


class _StubStore:
    """Placeholder for collections not yet implemented for local.
    Raises RuntimeError with a clear message so developers know what's missing.
    """

    def __init__(self, collection: str):
        self._collection = collection

    def __getattr__(self, name):
        raise RuntimeError(
            f"TinyDB store for '{self._collection}' is not yet implemented "
            f"(method: {name}). This collection is needed for the current "
            f"operation but only the MongoDB backend supports it."
        )


def _stub(name: str) -> _StubStore:
    return _StubStore(name)
