import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB
from .base import EvidenceList


class RepositoryEdge:
    def __init__(
        self,
        user_id: str,
        from_repository: str,
        to_repository_or_artifact: str,
        edge_type: str,
        source: str = "deterministic",
        confidence: float = 1.0,
        evidence: Optional[EvidenceList] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.from_repository = from_repository
        self.to_repository_or_artifact = to_repository_or_artifact
        self.edge_type = edge_type
        self.source = source
        self.confidence = confidence
        self.evidence = evidence or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "from_repository": self.from_repository,
            "to_repository_or_artifact": self.to_repository_or_artifact,
            "edge_type": self.edge_type,
            "source": self.source,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryEdge":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            from_repository=data.get("from_repository", ""),
            to_repository_or_artifact=data.get("to_repository_or_artifact", ""),
            edge_type=data.get("edge_type", ""),
            source=data.get("source", "deterministic"),
            confidence=data.get("confidence", 1.0),
            evidence=data.get("evidence", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryEdgeDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_edges")
        try:
            self.collection.create_index([("user_id", 1), ("from_repository", 1)])
            self.collection.create_index(
                [("user_id", 1), ("to_repository_or_artifact", 1)]
            )
            self.collection.create_index([("user_id", 1), ("edge_type", 1)])
        except Exception as exc:
            logging.debug("repository_edges index creation skipped: %s", exc)

    def replace_from_repository(
        self, user_id: str, from_repository: str, edges: List[RepositoryEdge]
    ) -> None:
        try:
            self.collection.delete_many(
                {"user_id": user_id, "from_repository": from_repository}
            )
            if edges:
                self.collection.insert_many([e.to_dict() for e in edges])
        except Exception as exc:
            logging.error("Error replacing repository_edges: %s", exc)
            raise

    def find_outgoing(self, user_id: str, from_repository: str) -> List[RepositoryEdge]:
        try:
            return [
                RepositoryEdge.from_dict(d)
                for d in self.collection.find(
                    {"user_id": user_id, "from_repository": from_repository}
                )
            ]
        except Exception as exc:
            logging.error("Error finding outgoing repository_edges: %s", exc)
            raise

    def find_incoming(
        self, user_id: str, to_repository_or_artifact: str
    ) -> List[RepositoryEdge]:
        try:
            return [
                RepositoryEdge.from_dict(d)
                for d in self.collection.find(
                    {
                        "user_id": user_id,
                        "to_repository_or_artifact": to_repository_or_artifact,
                    }
                )
            ]
        except Exception as exc:
            logging.error("Error finding incoming repository_edges: %s", exc)
            raise

    def delete_for_user(self, user_id: str) -> int:
        try:
            return self.collection.delete_many({"user_id": user_id}).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_edges: %s", exc)
            raise
