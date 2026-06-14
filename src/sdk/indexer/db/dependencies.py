import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB
from .base import EvidenceList


class RepositoryDependency:
    def __init__(
        self,
        user_id: str,
        repository_name: str,
        package_manager: str,
        name: str,
        name_normalized: Optional[str] = None,
        version_constraint: Optional[str] = None,
        version_resolved: Optional[str] = None,
        dependency_group: Optional[str] = None,
        source_file: Optional[str] = None,
        evidence: Optional[EvidenceList] = None,
        indexed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.repository_name = repository_name
        self.package_manager = package_manager
        self.name = name
        self.name_normalized = name_normalized or name.lower()
        self.version_constraint = version_constraint
        self.version_resolved = version_resolved
        self.dependency_group = dependency_group
        self.source_file = source_file
        self.evidence = evidence or []
        self.indexed_at = indexed_at or datetime.utcnow()
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "repository_name": self.repository_name,
            "package_manager": self.package_manager,
            "name": self.name,
            "name_normalized": self.name_normalized,
            "version_constraint": self.version_constraint,
            "version_resolved": self.version_resolved,
            "dependency_group": self.dependency_group,
            "source_file": self.source_file,
            "evidence": self.evidence,
            "indexed_at": self.indexed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryDependency":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            repository_name=data.get("repository_name", ""),
            package_manager=data.get("package_manager", ""),
            name=data.get("name", ""),
            name_normalized=data.get("name_normalized"),
            version_constraint=data.get("version_constraint"),
            version_resolved=data.get("version_resolved"),
            dependency_group=data.get("dependency_group"),
            source_file=data.get("source_file"),
            evidence=data.get("evidence", []),
            indexed_at=data.get("indexed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class RepositoryDependencyDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("repository_dependencies")
        try:
            self.collection.create_index([("user_id", 1), ("repository_name", 1)])
            self.collection.create_index(
                [("user_id", 1), ("name_normalized", 1), ("version_resolved", 1)]
            )
            self.collection.create_index([("user_id", 1), ("package_manager", 1)])
        except Exception as exc:
            logging.debug("repository_dependencies index creation skipped: %s", exc)

    def replace_for_repository(
        self, user_id: str, repository_name: str, deps: List[RepositoryDependency]
    ) -> None:
        try:
            self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            )
            if deps:
                self.collection.insert_many([d.to_dict() for d in deps])
        except Exception as exc:
            logging.error("Error replacing repository_dependencies: %s", exc)
            raise

    def find_for_repository(
        self, user_id: str, repository_name: str
    ) -> List[RepositoryDependency]:
        try:
            return [
                RepositoryDependency.from_dict(d)
                for d in self.collection.find(
                    {"user_id": user_id, "repository_name": repository_name}
                )
            ]
        except Exception as exc:
            logging.error("Error finding repository_dependencies: %s", exc)
            raise

    def find_repos_by_dependency(
        self,
        user_id: str,
        name_normalized: str,
        version_resolved: Optional[str] = None,
    ) -> List[str]:
        query: Dict[str, Any] = {
            "user_id": user_id,
            "name_normalized": name_normalized,
        }
        if version_resolved is not None:
            query["version_resolved"] = version_resolved
        try:
            cursor = self.collection.find(query, {"repository_name": 1})
            return list({d["repository_name"] for d in cursor})
        except Exception as exc:
            logging.error("Error finding repos by dependency: %s", exc)
            raise

    def delete_for_repository(self, user_id: str, repository_name: str) -> int:
        try:
            return self.collection.delete_many(
                {"user_id": user_id, "repository_name": repository_name}
            ).deleted_count
        except Exception as exc:
            logging.error("Error deleting repository_dependencies: %s", exc)
            raise
