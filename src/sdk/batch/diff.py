"""Per-repo diff collection — CLI run, chat, start_diffs orchestration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel
from git import Repo
from unidiff import PatchSet

from sdk.errors import ConflictError, NotFoundError
from sdk.batch.models import BatchSession, DiffState, FileStat, SubTask, Task

if TYPE_CHECKING:
    from sdk.storage.cache.base import Cache

from .cli_runner import ExternalRefusal, ResumableClaudeRunner
from .models import SimpleUserRequest
from . import tasks as _tasks_mod
from .workspace import clone_repo, repo_dir

logger = logging.getLogger(__name__)

_DIFF_SYSTEM_TEMPLATE = """\
You are making targeted code changes to a repository as part of a coordinated batch change.

Overall task:
{task_description}

Your specific changes for this repository:
{sub_task_description}

Make only the changes described above. Do not add tests unless explicitly asked.
Do not run git add, git commit, or git push. Stop when your edits are complete.
"""

# Appended to every edit-mode prompt (run_single_repo initial run and revise).
# NOT included in iterate_repo (Q&A) prompts so Claude stays conversational.
SUMMARY_INSTRUCTION = (
    "After completing your edits, reply with a plain-text summary of what you changed. "
    "One sentence if the change is small and expected; up to three sentences if the scope is large. "
    "Unless the sub-task description explicitly asks for more detail, keep it under three sentences. "
    "If you made no changes or hit a problem, explain why instead. "
    "No markdown, no preamble — just the summary text."
)


async def collect_git_diff(cwd: Path) -> tuple[dict[str, str], list[FileStat]]:
    """Return per-file diff strings and FileStat list from the working directory."""
    def _do_diff() -> str:
        r = Repo(str(cwd))
        return r.git.diff()

    raw = await asyncio.to_thread(_do_diff)
    if not raw.strip():
        return {}, []

    file_diffs: dict[str, str] = {}
    file_stats: list[FileStat] = []
    patch = PatchSet(raw)
    for pf in patch:
        path = pf.path
        lines = [line for hunk in pf for line in hunk]
        additions = sum(1 for l in lines if l.is_added)
        deletions = sum(1 for l in lines if l.is_removed)
        file_diffs[path] = str(pf)
        file_stats.append(FileStat(path=path, additions=additions, deletions=deletions))

    return file_diffs, file_stats


# ---------------------------------------------------------------------------
# Background task: run CLI on a single repo
# ---------------------------------------------------------------------------


async def run_single_repo(
    user_id: str,
    session_id: str,
    repo: str,
    task: Task,
    *,
    cache: "Cache",
    get_token: Callable[[], Awaitable[str]],
) -> None:
    """Background task: clone → run CLI → collect diff → store results."""
    sub = await cache.get_subtask(user_id, repo)
    if sub is None:
        logger.warning("run_single_repo: subtask %s/%s not found", user_id, repo)
        return

    try:
        token = await get_token()
        cwd = await clone_repo(user_id, session_id, repo, sub.branch, token)

        sub = sub.model_copy(update={"diff": DiffState(status="running", iteration=0)})
        await cache.set_subtask(user_id, repo, sub)

        system = _DIFF_SYSTEM_TEMPLATE.format(
            task_description=task.description,
            sub_task_description=sub.description,
        )
        runner = ResumableClaudeRunner()
        prompt = f"{sub.description}\n\n{SUMMARY_INSTRUCTION}"
        cli_session_id, result_text, _cost = await asyncio.to_thread(
            runner.run, cwd, prompt, system, None
        )
        await cache.set_cli_session(user_id, repo, cli_session_id, 0)

        file_diffs, file_stats = await collect_git_diff(cwd)
        await cache.set_raw_diff_many(user_id, repo, file_diffs)

        one_liner = result_text.strip() if result_text.strip() else "No changes detected"

        done = sub.model_copy(update={"diff": DiffState(
            status="ready",
            one_line_summary=one_liner,
            file_stats=file_stats,
            iteration=0,
            cli_session_id=cli_session_id,
        )})
        await cache.set_subtask(user_id, repo, done)
        logger.info("Diff ready for %s/%s", user_id, repo)

    except ExternalRefusal as exc:
        logger.warning("External refusal for %s/%s: %s", user_id, repo, exc)
        failed = sub.model_copy(update={"diff": DiffState(
            status="failed", error=str(exc), error_kind="external",
        )})
        await cache.set_subtask(user_id, repo, failed)
    except Exception:
        logger.exception("Diff failed for %s/%s", user_id, repo)
        failed = sub.model_copy(update={"diff": DiffState(
            status="failed", error="Internal error during diff (see server logs)", error_kind="internal",
        )})
        await cache.set_subtask(user_id, repo, failed)


# ---------------------------------------------------------------------------
# Diff orchestration
# ---------------------------------------------------------------------------


class ChatRepoRequest(BaseModel):
    user_id: str
    message: str
    mode: str


class ChatRepoResponse(BaseModel):
    status: str
    cli_response: Optional[str] = None
    session: Optional[BatchSession] = None


async def start_diffs(req: SimpleUserRequest, *, cache: "Cache", get_token: Callable[[], Awaitable[str]]) -> BatchSession:
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")

    for repo, sub in list(session.sub_tasks.items()):
        if sub.diff is not None and sub.diff.status not in ("pending",):
            continue

        cloning_sub = SubTask(
            repo=repo, branch=sub.branch, description=sub.description,
            diff=DiffState(status="cloning"),
            push=sub.push, pr_prep=sub.pr_prep, pr=sub.pr,
        )
        await cache.set_subtask(req.user_id, repo, cloning_sub)

        task = asyncio.create_task(
            run_single_repo(req.user_id, session.session_id, repo, session.task,
                            cache=cache, get_token=get_token),
            name=f"diff:{req.user_id}:{repo}",
        )
        _tasks_mod.register_repo(req.user_id, repo, task)

    return await cache.get_session(req.user_id)


async def chat_repo(repo: str, req: ChatRepoRequest, *, cache: "Cache") -> ChatRepoResponse:
    """Q&A (mode=qa) or edit (mode=edit) for a repo's diff via the CLI session."""
    session = await cache.get_session(req.user_id)
    if session is None:
        raise NotFoundError("No active batch session")
    sub = session.sub_tasks.get(repo)
    if sub is None:
        raise NotFoundError(f"Repo {repo!r} not in session")

    if sub.diff is None or sub.diff.cli_session_id is None:
        raise ConflictError("No CLI session for this repo; call start_diffs first")

    cwd = repo_dir(req.user_id, session.session_id, repo)
    if not cwd.exists():
        raise ConflictError("Workspace not found; workspace may have been wiped")

    try:
        runner = ResumableClaudeRunner()

        if req.mode == "qa":
            new_cli_id, result_text, _cost = await asyncio.to_thread(
                runner.run, cwd, req.message, None, sub.diff.cli_session_id
            )
            updated = SubTask(
                repo=repo, branch=sub.branch, description=sub.description,
                diff=DiffState(
                    status=sub.diff.status,
                    one_line_summary=sub.diff.one_line_summary,
                    file_stats=sub.diff.file_stats,
                    iteration=sub.diff.iteration,
                    cli_session_id=new_cli_id,
                    error=sub.diff.error,
                    error_kind=sub.diff.error_kind,
                ),
                push=sub.push, pr_prep=sub.pr_prep, pr=sub.pr,
            )
            await cache.set_subtask(req.user_id, repo, updated)
            return ChatRepoResponse(status="ok", cli_response=result_text)

        # mode == "edit"
        prompt = f"{req.message}\n\n{SUMMARY_INSTRUCTION}"
        new_cli_id, result_text, _cost = await asyncio.to_thread(
            runner.run, cwd, prompt, None, sub.diff.cli_session_id
        )
        new_iteration = (sub.diff.iteration or 0) + 1
        await cache.set_cli_session(req.user_id, repo, new_cli_id, new_iteration)

        file_diffs, file_stats = await collect_git_diff(cwd)
        await cache.set_raw_diff_many(req.user_id, repo, file_diffs)

        one_liner = result_text.strip() if result_text.strip() else "No changes detected"
        updated = SubTask(
            repo=repo, branch=sub.branch, description=sub.description,
            diff=DiffState(
                status="ready",
                one_line_summary=one_liner,
                file_stats=file_stats,
                iteration=new_iteration,
                cli_session_id=new_cli_id,
            ),
            push=sub.push, pr_prep=sub.pr_prep, pr=sub.pr,
        )
        await cache.set_subtask(req.user_id, repo, updated)
        updated_session = await cache.get_session(req.user_id)
        return ChatRepoResponse(status="ok", cli_response=one_liner, session=updated_session)

    except ExternalRefusal as exc:
        if req.mode == "edit":
            await cache.set_subtask(req.user_id, repo, SubTask(
                repo=repo, branch=sub.branch, description=sub.description,
                diff=DiffState(
                    status="failed", error=str(exc), error_kind="external",
                    iteration=sub.diff.iteration, cli_session_id=sub.diff.cli_session_id,
                    one_line_summary=sub.diff.one_line_summary,
                    file_stats=sub.diff.file_stats,
                ),
                push=sub.push, pr_prep=sub.pr_prep, pr=sub.pr,
            ))
        return ChatRepoResponse(status="failed", cli_response=str(exc))

    except Exception:
        logger.exception("chat_repo failed for %s/%s (mode=%s)", req.user_id, repo, req.mode)
        return ChatRepoResponse(status="failed", cli_response="Internal error (see server logs)")
