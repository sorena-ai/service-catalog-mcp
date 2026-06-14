"""Batch change workflow — plan → diff → push → pr lifecycle.

Public re-exports for each phase.
"""

from sdk.batch.models import BulkReposRequest, SimpleUserRequest

from sdk.batch.plan import (
    ProposeRequest,
    ReplanRequest,
    SetSubtaskRequest,
    add_repos,
    propose,
    remove_repos,
    replan,
    set_repo_subtask,
)

from sdk.batch.diff import (
    ChatRepoRequest,
    ChatRepoResponse,
    SUMMARY_INSTRUCTION,
    chat_repo,
    collect_git_diff,
    run_single_repo,
    start_diffs,
)

from sdk.batch.push import (
    PushReposRequest,
    pr_branch_name,
    push_repo,
    push_repos,
)

from sdk.batch.pr import (
    CreatePRPrepRequest,
    CreatePRRequest,
    SetPRPrepRequest,
    UpdatePRRequest,
    close_pr,
    create_pr,
    create_pr_prep,
    set_pr_prep,
    update_pr,
)

from sdk.batch.inspect import inspect_batch

from sdk.batch.ci import get_ci_status, get_ci_jobs
