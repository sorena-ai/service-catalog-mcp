"""Onboarding and user status tools."""

import base64
import os

from fastmcp import Context
from fastmcp.exceptions import ToolError

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import resolve_identity, ensure_installed, _LOCAL_MODE
from sdk.storage.db.mongo.repositories import UserRepository, UserRepositoryDB
from api.db.users import UserDB


@translate_sdk_errors
async def get_github_install_url(ctx: Context) -> dict:
    """Get the GitHub App installation URL for this user.

    Share this URL with the user so they can install the GitHub App OR
    configure an existing installation to add more repositories. If the
    user mentions missing repositories or wanting to add more, provide this link.
    After installation or configuration, repositories will be discovered and indexed automatically.
    """
    user_id, _ = await resolve_identity(ctx)
    github_app_name = os.getenv("GITHUB_APP_NAME", "service-catalog")
    state = base64.urlsafe_b64encode(user_id.encode()).decode()
    url = f"https://github.com/apps/{github_app_name}/installations/new?state={state}"
    return {"install_url": url, "user_id": user_id}


@translate_sdk_errors
async def index_repository(ctx: Context, repository_name: str) -> dict:
    """Queue a repository for indexing (or re-indexing if a previous attempt failed).

    Args:
        repository_name: Full repo name in owner/repo format.

    Returns status and task_id. Poll list_user_repositories() to track progress.
    """
    user_id, get_token = await resolve_identity(ctx)
    ensure_installed(user_id)

    if not _LOCAL_MODE:
        repo_db = UserRepositoryDB()
        if not repo_db.find_user_repository(user_id, repository_name):
            repo_db.add_user_repository(UserRepository(
                repository_name=repository_name,
                user_id=user_id,
                action="manual",
                is_indexed=False,
                indexing_status="pending",
            ))

    scheduler = ctx.lifespan_context["scheduler"]

    async def token_provider(_uid: str) -> str:
        return await get_token()

    result = await scheduler.trigger(
        user_id=user_id,
        repository_names=[repository_name],
        token_provider=token_provider,
        trigger="manual",
        bulk_limit=False,
    )
    return {"status": result["status"], "repository_name": repository_name}


@translate_sdk_errors
async def list_user_repositories(ctx: Context, indexed_only: bool = False) -> list:
    """List repositories available to the current user.

    Each repository includes an indexing_status field with one of:
      - pending   - discovered but not yet indexed
      - indexing  - indexing currently in progress
      - indexed   - fully indexed and ready for batch changes
      - failed    - last indexing attempt failed

    Args:
        indexed_only: If True, only return repositories with indexing_status == "indexed".
    """
    user_id, _ = await resolve_identity(ctx)

    user = UserDB().get_user_by_id(user_id)
    if not user:
        raise ToolError("Not found: User not found")

    repos = UserRepositoryDB().find_user_repositories(user_id)
    if indexed_only:
        repos = [r for r in repos if r.is_indexed]
    return [
        {
            "name": r.repository_name,
            "is_indexed": r.is_indexed,
            "indexing_status": r.indexing_status,
        }
        for r in repos
    ]
