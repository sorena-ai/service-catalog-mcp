import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    IN_REVIEW = "in-review"
    DONE = "done"
    CANCELLED = "cancelled"


class PullRequest(BaseModel):
    repository: str
    base_branch: str
    head_branch: str
    title: str
    body: str
    diff: str = ""
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    status: str = "pending"
    mergeable: Optional[bool] = None
    checks_status: Optional[str] = None
    last_checked: Optional[datetime] = None


class Task(BaseModel):
    user_id: str
    thread_id: str
    name: str = ""
    description: str = ""
    pull_requests: List[PullRequest] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    id: Optional[str] = None
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.TODO

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "name": self.name,
            "description": self.description,
            "pull_requests": [pr.dict() for pr in self.pull_requests],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "task_id": self.task_id,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        pull_requests = []
        if data.get("pull_requests"):
            try:
                for pr_data in data["pull_requests"]:
                    if all(f in pr_data for f in ["repository", "base_branch", "head_branch", "title", "body"]):
                        pull_requests.append(PullRequest(**pr_data))
                    else:
                        logging.warning("Skipping invalid PR entry: %s", pr_data)
            except Exception as e:
                logging.error("Error processing pull_requests: %s", e)

        status_value = data.get("status", "todo")
        if status_value == "pending":
            status_value = "todo"

        return cls(
            user_id=data.get("user_id", ""),
            thread_id=data.get("thread_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            pull_requests=pull_requests,
            created_at=data.get("created_at", datetime.utcnow()),
            updated_at=data.get("updated_at", datetime.utcnow()),
            id=str(data["_id"]) if data.get("_id") else None,
            task_id=data.get("task_id", str(uuid.uuid4())),
            status=TaskStatus(status_value),
        )
