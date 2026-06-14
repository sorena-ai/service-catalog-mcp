import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from lib.db.mongo import MongoDB

# ---------------------------------------------------------------------------
# UserRepository — keyed by user_id (not user_email)
# ---------------------------------------------------------------------------

class UserRepository:
    def __init__(
        self,
        repository_name: str,
        user_id: str,
        action: str,
        is_indexed: bool = False,
        indexing_status: str = "pending",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.repository_name = repository_name
        self.user_id = user_id
        self.action = action
        self.is_indexed = is_indexed
        self.indexing_status = indexing_status
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "repository_name": self.repository_name,
            "user_id": self.user_id,
            "action": self.action,
            "is_indexed": self.is_indexed,
            "indexing_status": self.indexing_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserRepository":
        return cls(
            _id=data.get("_id"),
            repository_name=data.get("repository_name", ""),
            user_id=data.get("user_id", ""),
            action=data.get("action", ""),
            is_indexed=data.get("is_indexed", False),
            indexing_status=data.get("indexing_status", "pending"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class UserRepositoryDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("user_repositories")

    def add_user_repository(self, user_repo: UserRepository) -> Dict[str, Any]:
        try:
            doc = user_repo.to_dict()
            result = self.collection.insert_one(doc)
            inserted = self.collection.find_one({"_id": result.inserted_id})
            if inserted:
                inserted["_id"] = str(inserted["_id"])
                for field in ("created_at", "updated_at"):
                    if isinstance(inserted.get(field), datetime):
                        inserted[field] = inserted[field].isoformat()
            return inserted or {**doc, "_id": str(result.inserted_id)}
        except Exception as e:
            logging.error("Error adding user_repository: %s", e)
            raise

    def find_user_repository(self, user_id: str, repository_name: str) -> Optional[UserRepository]:
        try:
            data = self.collection.find_one({"user_id": user_id, "repository_name": repository_name})
            return UserRepository.from_dict(data) if data else None
        except Exception as e:
            logging.error("Error finding user_repository: %s", e)
            raise

    def find_user_repositories(self, user_id: str) -> List[UserRepository]:
        try:
            docs = list(self.collection.find({"user_id": user_id}))
            return [UserRepository.from_dict(d) for d in docs]
        except Exception as e:
            logging.error("Error finding user_repositories: %s", e)
            raise

    def find_user_indexed_repositories(self, user_id: str) -> List[UserRepository]:
        try:
            docs = list(self.collection.find({"user_id": user_id, "is_indexed": True}))
            return [UserRepository.from_dict(d) for d in docs]
        except Exception as e:
            logging.error("Error finding indexed user_repositories: %s", e)
            raise

    def update_indexed_status(self, user_id: str, repository_name: str, is_indexed: bool, indexing_status: str = "indexed") -> bool:
        """Update index flags.

        ``indexing_status`` is one of: pending, indexing, indexed, failed.
        """
        try:
            result = self.collection.update_one(
                {"user_id": user_id, "repository_name": repository_name},
                {"$set": {"is_indexed": is_indexed, "indexing_status": indexing_status, "updated_at": datetime.utcnow()}},
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error("Error updating indexed_status: %s", e)
            raise

    def remove_user_repository(self, user_id: str, repository_name: str) -> bool:
        try:
            result = self.collection.delete_one({"user_id": user_id, "repository_name": repository_name})
            return result.deleted_count > 0
        except Exception as e:
            logging.error("Error removing user_repository: %s", e)
            raise

    def count_user_repositories(self, user_id: str) -> int:
        try:
            return self.collection.count_documents({"user_id": user_id})
        except Exception as e:
            logging.error("Error counting user_repositories: %s", e)
            raise

