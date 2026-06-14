from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


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
