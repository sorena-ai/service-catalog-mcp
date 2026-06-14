import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB


class CodebaseContext:
    def __init__(
        self,
        user_id: str,
        context_type: str,
        content: str,
        referenced_repositories: Optional[List[str]] = None,
        referenced_fact_ids: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.context_type = context_type
        self.content = content
        self.referenced_repositories = referenced_repositories or []
        self.referenced_fact_ids = referenced_fact_ids or []
        self.tags = tags or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "context_type": self.context_type,
            "content": self.content,
            "referenced_repositories": self.referenced_repositories,
            "referenced_fact_ids": self.referenced_fact_ids,
            "tags": self.tags,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodebaseContext":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            context_type=data.get("context_type", ""),
            content=data.get("content", ""),
            referenced_repositories=data.get("referenced_repositories", []),
            referenced_fact_ids=data.get("referenced_fact_ids", []),
            tags=data.get("tags", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class CodebaseContextDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("codebase_contexts")
        try:
            self.collection.create_index(
                [("user_id", 1), ("context_type", 1)], unique=True
            )
            self.collection.create_index([("content", "text")])
        except Exception as exc:
            logging.debug("codebase_contexts index creation skipped: %s", exc)

    def upsert(self, ctx: CodebaseContext) -> None:
        try:
            ctx.updated_at = datetime.utcnow()
            self.collection.update_one(
                {"user_id": ctx.user_id, "context_type": ctx.context_type},
                {"$set": ctx.to_dict()},
                upsert=True,
            )
        except Exception as exc:
            logging.error("Error upserting codebase_context: %s", exc)
            raise

    def find_for_user(
        self, user_id: str, context_types: Optional[List[str]] = None
    ) -> List[CodebaseContext]:
        query: Dict[str, Any] = {"user_id": user_id}
        if context_types:
            query["context_type"] = {"$in": context_types}
        try:
            return [
                CodebaseContext.from_dict(d) for d in self.collection.find(query)
            ]
        except Exception as exc:
            logging.error("Error finding codebase_contexts: %s", exc)
            raise

    def text_search(
        self,
        user_id: str,
        query_text: str,
        limit: int = 10,
    ) -> List[CodebaseContext]:
        query: Dict[str, Any] = {
            "user_id": user_id,
            "$text": {"$search": query_text},
        }
        try:
            cursor = (
                self.collection.find(query, {"score": {"$meta": "textScore"}})
                .sort([("score", {"$meta": "textScore"})])
                .limit(limit)
            )
            return [CodebaseContext.from_dict(d) for d in cursor]
        except Exception as exc:
            logging.error("Error running codebase_contexts text search: %s", exc)
            raise

    def delete_for_user(self, user_id: str) -> int:
        try:
            return self.collection.delete_many({"user_id": user_id}).deleted_count
        except Exception as exc:
            logging.error("Error deleting codebase_contexts: %s", exc)
            raise
