"""MCP server entrypoint — mode determined by LOCAL env var at startup.

LOCAL=true (default): single-user local mode (PAT, no Auth0, no billing tools).
LOCAL=false: cloud mode (Auth0 JWT, Mongo, multi-user, full tool set).

Run: python -m mcp_server.main
"""
from __future__ import annotations

import logging
import os
import sys

from mcp_server.app import _RO, _DEST, _IDEM, create_app
from mcp_server.identity import _LOCAL_MODE
from lib.tracing import setup_tracing

from mcp_server.tools.batch import (
    add_repos,
    cancel_batch,
    chat_repo,
    close_pr,
    create_pr,
    create_pr_prep,
    inspect_batch,
    propose_plan,
    push_repos,
    remove_repos,
    replan,
    set_pr_prep,
    set_repo_subtask,
    start_diffs,
    update_pr,
    wait_for_diffs,
)
from mcp_server.tools.search import (
    get_codebase_glossary,
    search_repos,
)
from mcp_server.tools.github import get_workflow_runs, get_workflow_jobs
from mcp_server.tools.onboarding import (
    get_github_install_url,
    index_repository,
    list_user_repositories,
)
from mcp_server.tools.billing import get_credit_balance

_BASE_TOOLS = [
    search_repos,
    get_codebase_glossary,
    index_repository,
    list_user_repositories,
    propose_plan,
    replan,
    set_repo_subtask,
    add_repos,
    remove_repos,
    start_diffs,
    chat_repo,
    wait_for_diffs,
    push_repos,
    create_pr_prep,
    set_pr_prep,
    create_pr,
    update_pr,
    close_pr,
    inspect_batch,
    cancel_batch,
    get_workflow_runs,
    get_workflow_jobs,
]

_ACCOUNT_TOOLS = [
    get_credit_balance,
    get_github_install_url,
]

_TOOL_ANNOTATIONS = {
    "search_repos": _RO,
    "get_codebase_glossary": _RO,
    "get_credit_balance": _RO,
    "get_github_install_url": _RO,
    "index_repository": _IDEM,
    "list_user_repositories": _RO,
    "propose_plan": _IDEM,
    "set_repo_subtask": _IDEM,
    "add_repos": _IDEM,
    "remove_repos": _DEST,
    "start_diffs": _IDEM,
    "wait_for_diffs": _RO,
    "push_repos": _DEST,
    "create_pr_prep": _IDEM,
    "set_pr_prep": _IDEM,
    "create_pr": _DEST,
    "close_pr": _DEST,
    "inspect_batch": _RO,
    "cancel_batch": _DEST,
    "get_workflow_runs": _RO,
    "get_workflow_jobs": _RO,
}

_LOCAL_INSTRUCTIONS = """
You are the Service Catalog assistant. Help users explore their codebase or make batch code changes across repos.

**Setup**: Ensure GITHUB_TOKEN and ANTHROPIC_API_KEY are set before proceeding.

## Discovery

Use search_repos to find repos by structured filter, NL query, or both. Call get_codebase_glossary
first when the user uses project-specific terms. Use list_user_repositories for a raw repo list.

## CI/CD pipeline status

Use get_workflow_runs for ANY question about build or pipeline status — regardless of vocabulary.
Call it without arguments after push_repos to check all pushed repos at once.
If a run has failed, call get_workflow_jobs(repository, run_id, failed_only=True) for step detail.

## Batch changes

Walk this sequence explicitly and conversationally. Always confirm before pushing or opening PRs.

1. **Find repos** — search_repos → confirm the list with the user.
2. **Plan** — propose_plan(query, repos=[…from step 1]).
   Display task.description and each repo's subtask description.
   Ask: "Does this plan look right?" Iterate with replan/set_repo_subtask until approved.
   **NEVER call start_diffs in the same turn as propose_plan.**
   Only after approval, ask: "Shall I start the diffs?" Then call start_diffs().
3. **Diff** — call wait_for_diffs() in a loop until every repo is terminal.
4. **Review** — show one_line_summary and file_stats per repo.
   Do NOT call inspect_batch(view="diff_file") unless the user explicitly asks for a specific file.
   Use chat_repo(mode="qa") for questions, chat_repo(mode="edit") for changes.
5. **Push** — push_repos, then call get_workflow_runs() to show CI status across all repos.
6. **PRs** — create_pr_prep → set_pr_prep → confirm → create_pr.

## Confirmation gates

Always confirm before: cancel_batch, push_repos with >1 repo, create_pr with >5 repos.

## Session reset

cancel_batch() wipes everything. Call propose_plan to start a new session.
""".strip()

_CLOUD_INSTRUCTIONS = """
You are the Service Catalog assistant. Help users explore their codebase or make batch code changes across repos.

Use search_repos to find repos by structured filter, NL query, or both. Call get_codebase_glossary
first when the user uses project-specific terms. Use list_user_repositories for a raw repo list.
When a tool returns "GitHub App is not installed", surface the install URL and ask the user to install it.

## CI/CD pipeline status

Use get_workflow_runs for ANY question about build or pipeline status — regardless of vocabulary.
This tool covers all of these phrasings (and more):
- "CI", "CD", "CICD", "pipeline", "build", "checks"
- "GitHub Actions", "workflows", "workflow runs", "Actions runs"
- "Did it pass?", "Is it green?", "Any failures?", "Status of the build"
- "Test results", "check status", "lint status"
- "What's running on the branch?", "Did my PR trigger a workflow?"

Call without arguments after push_repos to check all pushed repos at once.
For ad-hoc queries, pass repositories, branch, or pr_number as needed.
If a run has failed, call get_workflow_jobs(repository, run_id, failed_only=True) for step detail.
Summarise the result as: repo → run name → status/conclusion → link.

## Batch changes

Walk this sequence explicitly and conversationally. Always confirm before pushing or opening PRs.

1. **Find repos** — search_repos → confirm the list with the user.
2. **Plan** — propose_plan(query, repos=[…from step 1]).
   After the call, display:
   - The overall task description (task.description)
   - Each repo's subtask description (sub_tasks[repo].description)
   Ask: "Does this plan look right? You can ask me to adjust any repo's instructions before I start."
   Iterate with replan(hint), set_repo_subtask, add_repos, or remove_repos until the user approves.
   **NEVER call start_diffs in the same turn as propose_plan or replan.**
   Only after explicit user approval of the plan, ask: "Shall I start the diffs?"
   Call start_diffs() only after the user says yes.
3. **Diff** — call wait_for_diffs() in a loop until every repo is terminal (ready or failed).
   Read each progress tick aloud.
4. **Review** — show one_line_summary and file_stats per repo.
   Use chat_repo(mode="qa") for questions, chat_repo(mode="edit") for changes.
   Do NOT call inspect_batch(view="diff_file") unless the user explicitly asks to see a specific
   file's diff — raw diffs can be large and will pollute the context.
   When satisfied, ask: "Test on the pushed branch first, or skip straight to PRs?"
5a. **Test path** — push_repos(repos, branch) → get_workflow_runs() to show CI across all repos.
5b. **Skip path** — confirm explicitly ("CI still runs on the PR"), then push_repos.
6. **PRs** — create_pr_prep(repos) → set_pr_prep edits → confirm → create_pr(repos).
   After PR creation, call get_workflow_runs(repositories=[…], pr_number=…) to show CI status.

## Confirmation gates

Always confirm before: cancel_batch, push_repos with >1 repo, create_pr with >5 repos.

## Inspect at any time

inspect_batch(view) — readOnly; view="status"|"pr_status"|"diff_file". Call freely.

## Session reset

cancel_batch() wipes everything. Call propose_plan to start a new session.
""".strip()


def _build_auth():
    if _LOCAL_MODE:
        return None
    domain = os.getenv("MCP_AUTH0_DOMAIN", "")
    client_id = os.getenv("MCP_AUTH0_CLIENT_ID", "")
    client_secret = os.getenv("MCP_AUTH0_CLIENT_SECRET", "")
    if not domain or not client_id or not client_secret:
        logging.getLogger("mcp_server").warning(
            "MCP_AUTH0_* vars not set — running without authentication"
        )
        return None
    from fastmcp.server.auth.providers.auth0 import Auth0Provider
    return Auth0Provider(
        config_url=f"https://{domain}/.well-known/openid-configuration",
        client_id=client_id,
        client_secret=client_secret,
        audience=os.getenv("MCP_AUTH0_AUDIENCE") or None,
        base_url=os.getenv("MCP_BASE_URL", "http://localhost:8200"),
        require_authorization_consent="external",
    )


def _build_cache():
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        from sdk.storage.cache.redis import RedisCache
        return RedisCache(redis_url)
    from sdk.storage.cache.memory import MemoryCache
    return MemoryCache()


def _build_repos():
    if os.getenv("MONGODB_URI"):
        from sdk.storage.db.mongo.repositories import UserRepositoryDB
        return UserRepositoryDB()
    from sdk.storage.db.tiny.stores import TinyUserRepositoryStore
    return TinyUserRepositoryStore()


def main():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    setup_tracing("mcp-server")

    if _LOCAL_MODE:
        tools = _BASE_TOOLS
        instructions = _LOCAL_INSTRUCTIONS
        name = "service-catalog-local"
    else:
        tools = _BASE_TOOLS + _ACCOUNT_TOOLS
        instructions = _CLOUD_INSTRUCTIONS
        name = "service-catalog"

    app = create_app(
        name=name,
        instructions=instructions,
        auth=_build_auth(),
        tools=tools,
        tool_annotations=_TOOL_ANNOTATIONS,
        cache=_build_cache(),
        repos=_build_repos(),
    )

    port = int(os.getenv("MCP_PORT", "8200"))
    app.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
