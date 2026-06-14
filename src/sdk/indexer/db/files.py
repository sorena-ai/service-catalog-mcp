import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB
from .base import EvidenceList


class RepositoryFile:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        path: str,
        role: str,
        workspace_path: Optional[str] = None,
        language: Optional[str] = None,
        size_bytes: Optional[int] = None,
        fingerprint: Optional[str] = None,
        purpose: Optional[str] = None,
        evidence: Optional[EvidenceList] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.path = path
        self.role = role
        self.workspace_path = workspace_path
        self.language = language
        self.size_bytes = size_bytes
        self.fingerprint = fingerprint
        self.purpose = purpose
        self.evidence = evidence or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "path": self.path,
            "role": self.role,
            "workspace_path": self.workspace_path,
            "language": self.language,
            "size_bytes": self.size_bytes,
            "fingerprint": self.fingerprint,
            "purpose": self.purpose,
            "evidence": self.evidence,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryFile":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            path=data.get("path", ""),
            role=data.get("role", ""),
            workspace_path=data.get("workspace_path"),
            language=data.get("language"),
            size_bytes=data.get("size_bytes"),
            fingerprint=data.get("fingerprint"),
            purpose=data.get("purpose"),
            evidence=data.get("evidence", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryFileDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_files")
        try:
            self.collection.create_index([("user_id", 1), ("repository_name", 1)])
            self.collection.create_index([("user_id", 1), ("repository_name", 1), ("role", 1)])
        except Exception as exc:
            logging.debug("repository_files index creation skipped: %s", exc)

    def upsert(self, doc: RepositoryFile) -> None:
        try:
            doc.updated_at = datetime.utcnow()
            self.collection.update_one(
                {
                    "user_id": doc.user_id,
                    "repository_name": doc.repository_name,
                    "path": doc.path,
                },
                {"$set": doc.to_dict()},
                upsert=True,
            )
        except Exception as exc:
            logging.error("Error upserting repository_file: %s", exc)
            raise

    def replace_for_repository(self, user_id: str, repository_name: str, files: List[RepositoryFile]) -> None:
        try:
            self.collection.delete_many({"user_id": user_id, "repository_name": repository_name})
            if files:
                self.collection.insert_many([f.to_dict() for f in files])
        except Exception as exc:
            logging.error("Error replacing repository_files: %s", exc)
            raise

    def find_for_repository(
        self,
        user_id: str,
        repository_name: str,
        role: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> List[RepositoryFile]:
        query: Dict[str, Any] = {"user_id": user_id, "repository_name": repository_name}
        if role is not None:
            query["role"] = role
        if workspace_path is not None:
            query["workspace_path"] = workspace_path
        try:
            return [RepositoryFile.from_dict(d) for d in self.collection.find(query)]
        except Exception as exc:
            logging.error("Error finding repository_files: %s", exc)
            raise

    def delete_for_repository(self, user_id: str, repository_name: str) -> int:
        try:
            return self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            ).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_files: %s", exc)
            raise
