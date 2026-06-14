"""GitHub Actions MCP tools — workflow run status and job details."""
from __future__ import annotations

from typing import List, Optional

from fastmcp import Context
from pydantic import BaseModel, ConfigDict

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager
from sdk.batch.models import WorkflowJob, WorkflowRun


class RepoWorkflowRuns(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repository: str
    runs: List[WorkflowRun]
    status: Optional[str] = None
    conclusion: Optional[str] = None
    error: Optional[str] = None


class WorkflowRunsResult(BaseModel):
    """CI status across one or more repositories."""
    model_config = ConfigDict(extra="ignore")

    by_repo: List[RepoWorkflowRuns]
    total_runs: int


class WorkflowJobsResult(BaseModel):
    """Jobs for a single workflow run."""
    model_config = ConfigDict(extra="ignore")

    repository: str
    run_id: int
    jobs: List[WorkflowJob]


@translate_sdk_errors
async def get_workflow_runs(
    ctx: Context,
    repositories: Optional[List[str]] = None,
    branch: Optional[str] = None,
    pr_number: Optional[int] = None,
    limit: int = 10,
) -> WorkflowRunsResult:
    """Get GitHub Actions CI status across one or more repositories.

    Use this tool whenever users ask about:
    - CI / CD / CICD / pipeline status
    - GitHub Actions / workflows / checks / build status
    - "Did it pass?", "Is it green?", "Any failures?"
    - Workflow runs on a pushed branch or open PR

    If repositories is omitted, targets all repos with a successful push in the
    active batch session. Pass repositories explicitly for ad-hoc queries outside
    a session.

    Returns one entry per repo with aggregate status/conclusion and the individual
    runs. Each run includes logs_url — a direct link to logs, never fetch the content.

    Args:
        repositories: "owner/repo" list. Omit to use all pushed repos from session.
        branch: Branch name to filter runs.
        pr_number: PR number — resolves head SHA automatically.
        limit: Max runs per repo (default 10, max 100).
    """
    sm = await get_service_manager(ctx)
    by_repo_ci = await sm.get_ci_status(
        repos=repositories, branch=branch, pr_number=pr_number, limit=limit,
    )

    result_repos: List[RepoWorkflowRuns] = []
    total_runs = 0
    for repo, res in by_repo_ci.items():
        if res.ci is None:
            result_repos.append(RepoWorkflowRuns(
                repository=repo, runs=[], error=res.error or "Failed to fetch CI status",
            ))
        else:
            total_runs += len(res.ci.runs)
            result_repos.append(RepoWorkflowRuns(
                repository=repo,
                runs=res.ci.runs,
                status=res.ci.status,
                conclusion=res.ci.conclusion,
            ))

    return WorkflowRunsResult(by_repo=result_repos, total_runs=total_runs)


@translate_sdk_errors
async def get_workflow_jobs(
    ctx: Context,
    repository: str,
    run_id: int,
    failed_only: bool = False,
) -> WorkflowJobsResult:
    """Get per-job and per-step detail for a specific workflow run.

    Call this when a run has failed and you need to know which job or step
    broke. Each job includes an html_url that deep-links to its log in GitHub.

    Args:
        repository: Full repo name (owner/repo).
        run_id: Workflow run ID (from get_workflow_runs).
        failed_only: If True, return only failed/cancelled jobs. Default False.
    """
    sm = await get_service_manager(ctx)
    jobs = await sm.get_ci_jobs(repository, run_id)
    if failed_only:
        jobs = [
            j for j in jobs
            if j.conclusion in ("failure", "cancelled", "timed_out", "action_required")
        ]
    return WorkflowJobsResult(repository=repository, run_id=run_id, jobs=jobs)
