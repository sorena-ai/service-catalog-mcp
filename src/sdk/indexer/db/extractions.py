import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB
from .base import EvidenceList


class RepositoryExtraction:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        extraction_type: str,
        data: Optional[Dict[str, Any]] = None,
        workspace_path: Optional[str] = None,
        evidence: Optional[EvidenceList] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.extraction_type = extraction_type
        self.data = data or {}
        self.workspace_path = workspace_path
        self.evidence = evidence or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "extraction_type": self.extraction_type,
            "data": self.data,
            "workspace_path": self.workspace_path,
            "evidence": self.evidence,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            doc["_id"] = self._id
        return doc

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryExtraction":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            extraction_type=data.get("extraction_type", ""),
            data=data.get("data", {}),
            workspace_path=data.get("workspace_path"),
            evidence=data.get("evidence", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryExtractionDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_extractions")
        try:
            self.collection.create_index(
                [("user_id", 1), ("repository_name", 1), ("extraction_type", 1)]
            )
            # Per-extraction-type secondary indexes on common data.* lookup keys.
            self.collection.create_index(
                [
                    ("user_id", 1),
                    ("extraction_type", 1),
                    ("data.image_name", 1),
                    ("data.tag", 1),
                ]
            )
            self.collection.create_index(
                [
                    ("user_id", 1),
                    ("extraction_type", 1),
                    ("data.action_owner", 1),
                    ("data.action_name", 1),
                    ("data.version_ref", 1),
                ]
            )
            self.collection.create_index(
                [
                    ("user_id", 1),
                    ("extraction_type", 1),
                    ("data.framework", 1),
                    ("data.language", 1),
                ]
            )
            self.collection.create_index(
                [("user_id", 1), ("extraction_type", 1), ("data.platform", 1)]
            )
        except Exception as exc:
            logging.debug("repository_extractions index creation skipped: %s", exc)

    def replace_for_repository_type(
        self,
        user_id: str,
        repository_name: str,
        extraction_type: str,
        rows: List[RepositoryExtraction],
    ) -> None:
        try:
            self.collection.delete_many(
                {
                    "user_id": user_id,
                    "repository_name": repository_name,
                    "extraction_type": extraction_type,
                }
            )
            if rows:
                self.collection.insert_many([r.to_dict() for r in rows])
        except Exception as exc:
            logging.error("Error replacing repository_extractions: %s", exc)
            raise

    def find_for_repository(
        self,
        user_id: str,
        repository_name: str,
        extraction_type: Optional[str] = None,
    ) -> List[RepositoryExtraction]:
        query: Dict[str, Any] = {
            "user_id": user_id,
            "repository_name": repository_name,
        }
        if extraction_type is not None:
            query["extraction_type"] = extraction_type
        try:
            return [
                RepositoryExtraction.from_dict(d) for d in self.collection.find(query)
            ]
        except Exception as exc:
            logging.error("Error finding repository_extractions: %s", exc)
            raise

    def find(
        self,
        user_id: str,
        extraction_type: str,
        data_filters: Optional[Dict[str, Any]] = None,
    ) -> List[RepositoryExtraction]:
        query: Dict[str, Any] = {
            "user_id": user_id,
            "extraction_type": extraction_type,
        }
        if data_filters:
            for k, v in data_filters.items():
                query[f"data.{k}"] = v
        try:
            return [
                RepositoryExtraction.from_dict(d) for d in self.collection.find(query)
            ]
        except Exception as exc:
            logging.error("Error finding repository_extractions: %s", exc)
            raise

    def delete_for_repository(self, user_id: str, repository_name: str) -> int:
        try:
            return self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            ).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_extractions: %s", exc)
            raise
