"""Shared models and request types for the batch workflow."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# Request types
# ---------------------------------------------------------------------------

class SimpleUserRequest(BaseModel):
    user_id: str


class BulkReposRequest(BaseModel):
    user_id: str
    repos: List[str]

    @field_validator("repos")
    @classmethod
    def repos_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("repos must not be empty")
        return v


# ---------------------------------------------------------------------------
# Session models
# ---------------------------------------------------------------------------

class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str


class Hint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    at: datetime


class FileStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    additions: int
    deletions: int


class DiffState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "cloning", "running", "ready", "failed"] = "pending"
    one_line_summary: Optional[str] = None
    file_stats: list[FileStat] = []
    error: Optional[str] = None
    error_kind: Optional[Literal["internal", "external"]] = None
    iteration: int = 0
    cli_session_id: Optional[str] = None


class WorkflowRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    status: str
    conclusion: Optional[str] = None
    display_title: Optional[str] = None
    path: Optional[str] = None
    run_number: Optional[int] = None
    run_attempt: Optional[int] = None
    run_started_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    event: Optional[str] = None
    head_branch: Optional[str] = None
    head_sha: Optional[str] = None
    actor: Optional[str] = None
    html_url: str
    logs_url: Optional[str] = None
    pull_requests: list[int] = []


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    status: str
    conclusion: Optional[str] = None
    number: int


class WorkflowJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    status: str
    conclusion: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    html_url: str
    steps: list[WorkflowStep] = []


class CIState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["queued", "in_progress", "completed"]
    conclusion: Optional[Literal[
        "success", "failure", "neutral", "cancelled",
        "timed_out", "action_required", "skipped",
    ]] = None
    runs: list[WorkflowRun] = []
    polled_at: datetime


class PR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    url: str
    state: Literal["open", "closed", "merged"]
    is_draft: bool
    opened_at: datetime


class PushState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pushing", "pushed", "failed"] = "pushed"
    branch: str
    pushed_sha: Optional[str] = None
    at: datetime
    error: Optional[str] = None
    ci: Optional[CIState] = None


class PRPrep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str
    head_branch: str
    base_branch: str


class SubTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    branch: str
    description: str
    diff: Optional[DiffState] = None
    push: Optional[PushState] = None
    pr_prep: Optional[PRPrep] = None
    pr: Optional[PR] = None


class BatchSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    session_id: str
    query: str
    task: Task
    history: list[Hint] = []
    sub_tasks: dict[str, SubTask] = {}
    created_at: datetime


InspectView = Literal["status", "pr_status", "diff_file"]
StatusFormat = Literal["concise", "detailed"]


class SubTaskConcise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["plan", "diff", "push", "pr"]
    diff_status: Optional[str] = None
    push_status: Optional[str] = None
    pr_url: Optional[str] = None


class BatchSessionConcise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    task: Task
    sub_tasks: dict[str, SubTaskConcise]

    @classmethod
    def from_session(cls, session: "BatchSession") -> "BatchSessionConcise":
        concise_subs: dict[str, SubTaskConcise] = {}
        for repo, sub in session.sub_tasks.items():
            if sub.pr is not None:
                phase: Literal["plan", "diff", "push", "pr"] = "pr"
            elif sub.push is not None:
                phase = "push"
            elif sub.diff is not None:
                phase = "diff"
            else:
                phase = "plan"
            concise_subs[repo] = SubTaskConcise(
                phase=phase,
                diff_status=sub.diff.status if sub.diff else None,
                push_status=sub.push.status if sub.push else None,
                pr_url=sub.pr.url if sub.pr else None,
            )
        return cls(user_id=session.user_id, task=session.task, sub_tasks=concise_subs)
