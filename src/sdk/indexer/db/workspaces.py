import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB
from .base import EvidenceList


class RepositoryWorkspace:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        workspace_path: str,
        manifest_files: Optional[List[str]] = None,
        detected_language: Optional[str] = None,
        detected_framework: Optional[str] = None,
        detected_package_manager: Optional[str] = None,
        evidence: Optional[EvidenceList] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.workspace_path = workspace_path
        self.manifest_files = manifest_files or []
        self.detected_language = detected_language
        self.detected_framework = detected_framework
        self.detected_package_manager = detected_package_manager
        self.evidence = evidence or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "workspace_path": self.workspace_path,
            "manifest_files": self.manifest_files,
            "detected_language": self.detected_language,
            "detected_framework": self.detected_framework,
            "detected_package_manager": self.detected_package_manager,
            "evidence": self.evidence,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryWorkspace":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            workspace_path=data.get("workspace_path", ""),
            manifest_files=data.get("manifest_files", []),
            detected_language=data.get("detected_language"),
            detected_framework=data.get("detected_framework"),
            detected_package_manager=data.get("detected_package_manager"),
            evidence=data.get("evidence", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryWorkspaceDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_workspaces")
        try:
            self.collection.create_index([("user_id", 1), ("repository_name", 1)])
            self.collection.create_index(
                [("user_id", 1), ("repository_name", 1), ("workspace_path", 1)],
                unique=True,
            )
        except Exception as exc:
            logging.debug("repository_workspaces index creation skipped: %s", exc)

    def replace_for_repository(
        self, user_id: str, repository_name: str, workspaces: List[RepositoryWorkspace]
    ) -> None:
        try:
            self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            )
            if workspaces:
                self.collection.insert_many([w.to_dict() for w in workspaces])
        except Exception as exc:
            logging.error("Error replacing repository_workspaces: %s", exc)
            raise

    def find_for_repository(
        self, user_id: str, repository_name: str
    ) -> List[RepositoryWorkspace]:
        try:
            return [
                RepositoryWorkspace.from_dict(d)
                for d in self.collection.find(
                    {"user_id": user_id, "repository_name": repository_name}
                )
            ]
        except Exception as exc:
            logging.error("Error finding repository_workspaces: %s", exc)
            raise

    def find_repos_with_manifest(self, user_id: str, manifest_filename: str) -> List[str]:
        try:
            cursor = self.collection.find(
                {"user_id": user_id, "manifest_files": manifest_filename},
                {"repository_name": 1},
            )
            return list({d["repository_name"] for d in cursor})
        except Exception as exc:
            logging.error("Error finding repos with manifest: %s", exc)
            raise

    def delete_for_repository(self, user_id: str, repository_name: str) -> int:
        try:
            return self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            ).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_workspaces: %s", exc)
            raise
