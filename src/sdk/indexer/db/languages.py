import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB
from .base import EvidenceList


class RepositoryLanguage:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        language: str,
        confidence: float = 1.0,
        evidence: Optional[EvidenceList] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.language = language
        self.confidence = confidence
        self.evidence = evidence or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "language": self.language,
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
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryLanguage":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            language=data.get("language", ""),
            confidence=data.get("confidence", 1.0),
            evidence=data.get("evidence", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryLanguageDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_languages")
        try:
            self.collection.create_index([("user_id", 1), ("repository_name", 1)])
            self.collection.create_index([("user_id", 1), ("language", 1)])
        except Exception as exc:
            logging.debug("repository_languages index creation skipped: %s", exc)

    def replace_for_repository(
        self, user_id: str, repository_name: str, languages: List[RepositoryLanguage]
    ) -> None:
        try:
            self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            )
            if languages:
                self.collection.insert_many([lang.to_dict() for lang in languages])
        except Exception as exc:
            logging.error("Error replacing repository_languages: %s", exc)
            raise

    def find_for_repository(
        self, user_id: str, repository_name: str
    ) -> List[RepositoryLanguage]:
        try:
            return [
                RepositoryLanguage.from_dict(d)
                for d in self.collection.find(
                    {"user_id": user_id, "repository_name": repository_name}
                )
            ]
        except Exception as exc:
            logging.error("Error finding repository_languages: %s", exc)
            raise

    def find_repos_by_language(self, user_id: str, language: str) -> List[str]:
        try:
            cursor = self.collection.find(
                {"user_id": user_id, "language": language},
                {"repository_name": 1},
            )
            return list({d["repository_name"] for d in cursor})
        except Exception as exc:
            logging.error("Error finding repos by language: %s", exc)
            raise

    def delete_for_repository(self, user_id: str, repository_name: str) -> int:
        try:
            return self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            ).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_languages: %s", exc)
            raise
