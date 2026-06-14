import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB

# NOTE: Mongo doc limit is 16MB. ~100k paths × ~80 chars approaches that
# limit. If a monorepo trips it we'll either truncate or shard into a
# repository_tree_chunks collection. Not handled in step 1.


class RepositoryTree:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        paths: Optional[List[str]] = None,
        file_count: Optional[int] = None,
        depth_max: Optional[int] = None,
        fingerprint: Optional[str] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.paths = paths or []
        self.file_count = file_count if file_count is not None else len(self.paths)
        self.depth_max = depth_max if depth_max is not None else _max_depth(self.paths)
        self.fingerprint = fingerprint
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "paths": self.paths,
            "file_count": self.file_count,
            "depth_max": self.depth_max,
            "fingerprint": self.fingerprint,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryTree":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            paths=data.get("paths", []),
            file_count=data.get("file_count"),
            depth_max=data.get("depth_max"),
            fingerprint=data.get("fingerprint"),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


def _max_depth(paths: List[str]) -> int:
    return max((p.count("/") for p in paths), default=0)


class RepositoryTreeDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_trees")
        try:
            self.collection.create_index(
                [("user_id", 1), ("repository_name", 1)], unique=True
            )
        except Exception as exc:
            logging.debug("repository_trees index creation skipped: %s", exc)

    def upsert(self, tree: RepositoryTree) -> None:
        try:
            tree.updated_at = datetime.utcnow()
            self.collection.update_one(
                {"user_id": tree.user_id, "repository_name": tree.repository_name},
                {"$set": tree.to_dict()},
                upsert=True,
            )
        except Exception as exc:
            logging.error("Error upserting repository_tree: %s", exc)
            raise

    def get(self, user_id: str, repository_name: str) -> Optional[RepositoryTree]:
        try:
            data = self.collection.find_one(
                {"user_id": user_id, "repository_name": repository_name}
            )
            return RepositoryTree.from_dict(data) if data else None
        except Exception as exc:
            logging.error("Error getting repository_tree: %s", exc)
            raise

    def find_repos_with_path_pattern(self, user_id: str, pattern: str) -> List[str]:
        """Return repository_names whose tree contains a path matching the regex."""
        try:
            regex = re.compile(pattern)
            cursor = self.collection.find(
                {"user_id": user_id, "paths": {"$regex": regex}},
                {"repository_name": 1},
            )
            return [d["repository_name"] for d in cursor]
        except Exception as exc:
            logging.error("Error matching repository_tree paths: %s", exc)
            raise

    def delete(self, user_id: str, repository_name: str) -> bool:
        try:
            result = self.collection.delete_one(
                {"user_id": user_id, "repository_name": repository_name}
            )
            return result.deleted_count > 0
        except Exception as exc:
            logging.error("Error deleting repository_tree: %s", exc)
            raise
