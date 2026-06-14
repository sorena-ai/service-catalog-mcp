"""GitHub Actions REST — workflow runs and jobs."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from lib.github.models import CIState, WorkflowJob, WorkflowRun, WorkflowStep

_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", **_GH_HEADERS}


async def get_workflow_runs(
    token: str,
    repo: str,
    head_sha: str | None = None,
    branch: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return workflow runs filtered by head SHA or branch."""
    params: dict = {"per_page": min(limit, 100)}
    if head_sha is not None:
        params["head_sha"] = head_sha
    elif branch is not None:
        params["branch"] = branch

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            headers=_headers(token),
            params=params,
        )
        resp.raise_for_status()

    return [_map_run(r) for r in resp.json().get("workflow_runs", [])[:limit]]


async def get_workflow_jobs(
    token: str,
    repo: str,
    run_id: int,
) -> list[dict]:
    """Return jobs for a workflow run."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs",
            headers=_headers(token),
            params={"per_page": 100},
        )
        resp.raise_for_status()

    return [_map_job(j) for j in resp.json().get("jobs", [])]


async def fetch_workflow_runs(
    repo: str,
    token: str,
    head_sha: str | None = None,
    branch: str | None = None,
    limit: int = 10,
) -> CIState:
    """Fetch workflow runs and return an aggregate CIState snapshot."""
    runs_data = await get_workflow_runs(token, repo, head_sha=head_sha, branch=branch, limit=limit)
    runs = [WorkflowRun(**r) for r in runs_data]

    if not runs:
        return CIState(
            status="completed",
            conclusion=None,
            runs=[],
            polled_at=datetime.now(timezone.utc),
        )

    statuses = {r.status for r in runs}
    if "in_progress" in statuses:
        agg_status: str = "in_progress"
    elif statuses & {"queued", "waiting", "pending", "requested"}:
        agg_status = "queued"
    else:
        agg_status = "completed"

    agg_conclusion: str | None = None
    if agg_status == "completed":
        conclusions = {r.conclusion for r in runs if r.conclusion}
        if conclusions & {"failure", "timed_out", "action_required"}:
            agg_conclusion = "failure"
        elif "cancelled" in conclusions:
            agg_conclusion = "cancelled"
        elif conclusions and not conclusions - {"success", "skipped", "neutral", "stale"}:
            agg_conclusion = "success"
        else:
            agg_conclusion = "neutral"

    return CIState(
        status=agg_status,
        conclusion=agg_conclusion,
        runs=runs,
        polled_at=datetime.now(timezone.utc),
    )


async def fetch_workflow_jobs(
    repo: str,
    run_id: int,
    token: str,
) -> list[WorkflowJob]:
    """Fetch jobs for a workflow run."""
    jobs_data = await get_workflow_jobs(token, repo, run_id)
    return [
        WorkflowJob(
            id=j["id"],
            name=j["name"],
            status=j["status"],
            conclusion=j.get("conclusion"),
            started_at=j.get("started_at"),
            completed_at=j.get("completed_at"),
            html_url=j["html_url"],
            steps=[WorkflowStep(**s) for s in j.get("steps", [])],
        )
        for j in jobs_data
    ]


def _map_run(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "status": r["status"],
        "conclusion": r.get("conclusion"),
        "display_title": r.get("display_title"),
        "path": r.get("path"),
        "run_number": r.get("run_number"),
        "run_attempt": r.get("run_attempt"),
        "run_started_at": r.get("run_started_at"),
        "created_at": r["created_at"],
        "updated_at": r.get("updated_at"),
        "event": r.get("event"),
        "head_branch": r.get("head_branch"),
        "head_sha": r.get("head_sha"),
        "actor": r["actor"]["login"] if r.get("actor") else None,
        "html_url": r["html_url"],
        "logs_url": r.get("logs_url"),
        "pull_requests": [pr["number"] for pr in r.get("pull_requests", [])],
    }


def _map_job(j: dict) -> dict:
    return {
        "id": j["id"],
        "name": j["name"],
        "status": j["status"],
        "conclusion": j.get("conclusion"),
        "started_at": j.get("started_at"),
        "completed_at": j.get("completed_at"),
        "html_url": j["html_url"],
        "steps": [
            {
                "name": s["name"],
                "status": s["status"],
                "conclusion": s.get("conclusion"),
                "number": s["number"],
            }
            for s in j.get("steps", [])
        ],
    }
