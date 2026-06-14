import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime
from bson import ObjectId
from lib.db.mongo import MongoDB

if TYPE_CHECKING:
    from lib.db.tasks import Task


class TaskDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("tasks")

    def get_task(self, task_id: str) -> Optional["Task"]:
        try:
            from lib.db.tasks import Task
            data = self.collection.find_one({"_id": ObjectId(task_id)})
            if data:
                data["_id"] = str(data["_id"])
                return Task.from_dict(data)
            return None
        except Exception as e:
            logging.error("Error getting task: %s", e)
            raise

    def get_tasks_by_user(self, user_id: str) -> List["Task"]:
        try:
            from lib.db.tasks import Task
            tasks_data = list(self.collection.find({"user_id": user_id}))
            for t in tasks_data:
                t["_id"] = str(t["_id"])
            return [Task.from_dict(t) for t in tasks_data]
        except Exception as e:
            logging.error("Error getting tasks by user: %s", e)
            raise

    def get_task_by_thread(self, thread_id: str) -> Optional["Task"]:
        try:
            from lib.db.tasks import Task
            data = self.collection.find_one({"thread_id": thread_id})
            if data:
                data["_id"] = str(data["_id"])
                return Task.from_dict(data)
            return None
        except Exception as e:
            logging.error("Error getting task by thread: %s", e)
            raise

    def create_task(self, task: "Task") -> str:
        try:
            result = self.collection.insert_one(task.to_dict())
            return str(result.inserted_id)
        except Exception as e:
            logging.error("Error creating task: %s", e)
            raise

    def update_task(self, task_id: str, update_data: Dict[str, Any]) -> bool:
        try:
            update_data["updated_at"] = datetime.utcnow()
            result = self.collection.update_one(
                {"_id": ObjectId(task_id)},
                {"$set": update_data},
            )
            return result.modified_count > 0
        except Exception as e:
            logging.error("Error updating task: %s", e)
            raise

    def update_task_pr_url(self, task_id: str, pr_index: int, pr_url: str) -> bool:
        try:
            result = self.collection.update_one(
                {"_id": ObjectId(task_id)},
                {"$set": {f"pull_requests.{pr_index}.pr_url": pr_url, "updated_at": datetime.utcnow()}},
            )
            return result.modified_count > 0
        except Exception as e:
            logging.error("Error updating task pr_url: %s", e)
            raise

    def delete_task(self, task_id: str) -> bool:
        try:
            result = self.collection.delete_one({"_id": ObjectId(task_id)})
            return result.deleted_count > 0
        except Exception as e:
            logging.error("Error deleting task: %s", e)
            raise
