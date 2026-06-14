import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB


class RepositoryContext:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        context_type: str,
        content: str,
        workspace_path: Optional[str] = None,
        tags: Optional[List[str]] = None,
        paths: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        referenced_fact_ids: Optional[List[str]] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.context_type = context_type
        self.content = content
        self.workspace_path = workspace_path
        self.tags = tags or []
        self.paths = paths or []
        self.symbols = symbols or []
        self.referenced_fact_ids = referenced_fact_ids or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "context_type": self.context_type,
            "content": self.content,
            "workspace_path": self.workspace_path,
            "tags": self.tags,
            "paths": self.paths,
            "symbols": self.symbols,
            "referenced_fact_ids": self.referenced_fact_ids,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryContext":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            context_type=data.get("context_type", ""),
            content=data.get("content", ""),
            workspace_path=data.get("workspace_path"),
            tags=data.get("tags", []),
            paths=data.get("paths", []),
            symbols=data.get("symbols", []),
            referenced_fact_ids=data.get("referenced_fact_ids", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryContextDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_contexts")
        try:
            self.collection.create_index(
                [("user_id", 1), ("repository_name", 1), ("context_type", 1)]
            )
            self.collection.create_index([("content", "text")])
        except Exception as exc:
            logging.debug("repository_contexts index creation skipped: %s", exc)

    def upsert(self, ctx: RepositoryContext) -> None:
        try:
            ctx.updated_at = datetime.utcnow()
            self.collection.update_one(
                {
                    "user_id": ctx.user_id,
                    "repository_name": ctx.repository_name,
                    "context_type": ctx.context_type,
                    "workspace_path": ctx.workspace_path,
                },
                {"$set": ctx.to_dict()},
                upsert=True,
            )
        except Exception as exc:
            logging.error("Error upserting repository_context: %s", exc)
            raise

    def replace_for_repository(
        self, user_id: str, repository_name: str, contexts: List[RepositoryContext]
    ) -> None:
        try:
            self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            )
            if contexts:
                self.collection.insert_many([c.to_dict() for c in contexts])
        except Exception as exc:
            logging.error("Error replacing repository_contexts: %s", exc)
            raise

    def find_for_repository(
        self,
        user_id: str,
        repository_name: str,
        context_types: Optional[List[str]] = None,
        workspace_path: Optional[str] = None,
    ) -> List[RepositoryContext]:
        query: Dict[str, Any] = {
            "user_id": user_id,
            "repository_name": repository_name,
        }
        if context_types:
            query["context_type"] = {"$in": context_types}
        if workspace_path is not None:
            query["workspace_path"] = workspace_path
        try:
            return [
                RepositoryContext.from_dict(d) for d in self.collection.find(query)
            ]
        except Exception as exc:
            logging.error("Error finding repository_contexts: %s", exc)
            raise

    def text_search(
        self,
        user_id: str,
        query_text: str,
        context_types: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[RepositoryContext]:
        query: Dict[str, Any] = {
            "user_id": user_id,
            "$text": {"$search": query_text},
        }
        if context_types:
            query["context_type"] = {"$in": context_types}
        try:
            cursor = (
                self.collection.find(query, {"score": {"$meta": "textScore"}})
                .sort([("score", {"$meta": "textScore"})])
                .limit(limit)
            )
            return [RepositoryContext.from_dict(d) for d in cursor]
        except Exception as exc:
            logging.error("Error running repository_contexts text search: %s", exc)
            raise

    def delete_for_repository(self, user_id: str, repository_name: str) -> int:
        try:
            return self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            ).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_contexts: %s", exc)
            raise
