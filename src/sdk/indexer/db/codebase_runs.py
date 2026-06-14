import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from lib.db.mongo import MongoDB


class CodebaseRun:
    def __init__(
        self,
        user_id: str,
        status: str,
        trigger: str,
        input_repository_names: Optional[List[str]] = None,
        clone_dir: Optional[str] = None,
        model_version: Optional[str] = None,
        cost_usd: float = 0.0,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.user_id = user_id
        self.status = status
        self.trigger = trigger
        self.input_repository_names = input_repository_names or []
        self.clone_dir = clone_dir
        self.model_version = model_version
        self.cost_usd = cost_usd
        self.error_message = error_message
        self.started_at = started_at
        self.completed_at = completed_at
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "user_id": self.user_id,
            "status": self.status,
            "trigger": self.trigger,
            "input_repository_names": self.input_repository_names,
            "clone_dir": self.clone_dir,
            "model_version": self.model_version,
            "cost_usd": self.cost_usd,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id is not None:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodebaseRun":
        return cls(
            _id=data.get("_id"),
            user_id=data.get("user_id", ""),
            status=data.get("status", ""),
            trigger=data.get("trigger", ""),
            input_repository_names=data.get("input_repository_names", []),
            clone_dir=data.get("clone_dir"),
            model_version=data.get("model_version"),
            cost_usd=data.get("cost_usd", 0.0),
            error_message=data.get("error_message"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class CodebaseRunDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("codebase_runs")
        try:
            self.collection.create_index([("user_id", 1), ("created_at", -1)])
            self.collection.create_index([("user_id", 1), ("status", 1)])
        except Exception as exc:
            logging.debug("codebase_runs index creation skipped: %s", exc)

    def insert(self, run: CodebaseRun) -> str:
        try:
            result = self.collection.insert_one(run.to_dict())
            run._id = result.inserted_id
            return str(result.inserted_id)
        except Exception as exc:
            logging.error("Error inserting codebase_run: %s", exc)
            raise

    def update(self, run_id: str, fields: Dict[str, Any]) -> bool:
        from bson import ObjectId

        try:
            fields = {**fields, "updated_at": datetime.utcnow()}
            result = self.collection.update_one(
                {"_id": ObjectId(run_id)}, {"$set": fields}
            )
            return result.matched_count > 0
        except Exception as exc:
            logging.error("Error updating codebase_run: %s", exc)
            raise

    def get_latest(self, user_id: str) -> Optional[CodebaseRun]:
        try:
            data = self.collection.find_one(
                {"user_id": user_id}, sort=[("created_at", -1)]
            )
            return CodebaseRun.from_dict(data) if data else None
        except Exception as exc:
            logging.error("Error getting latest codebase_run: %s", exc)
            raise
