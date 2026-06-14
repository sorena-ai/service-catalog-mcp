"""GitHub App integration — callback and webhook only."""

import base64
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from lib.github.client import installation_token_for_id
from api.db.github_users import GithubUser, GithubUserDB
from api.db.users import UserDB
from sdk.storage.db.mongo.repositories import UserRepository, UserRepositoryDB

router = APIRouter(prefix="/github")

GITHUB_APP_NAME = os.getenv("GITHUB_APP_NAME", "service-catalog")


def _render_install_status_page(user_id: str, state: str) -> str:
    page = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Service Catalog — Indexing repositories</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 72px auto; padding: 0 24px; color: #111; }
    h1 { font-size: 28px; margin: 0 0 12px; }
    p { color: #444; line-height: 1.5; }
    .card { border: 1px solid #e5e5e5; border-radius: 14px; padding: 18px; margin-top: 22px; }
    .phase { font-weight: 650; margin-bottom: 14px; }
    .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #ddd; border-top-color: #111; border-radius: 50%; animation: spin 0.9s linear infinite; vertical-align: -2px; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <h1>Connected to GitHub ✓</h1>
  <p>Your repositories are being indexed. You can start using Service Catalog in Claude Desktop shortly.</p>
  <div class="card">
    <div class="phase"><span class="spinner"></span>&nbsp; Indexing repositories…</div>
  </div>
</body>
</html>"""
    return page


@router.get("/callback")
async def github_callback(
    installation_id: int,
    setup_action: str,
    state: str,
):
    try:
        user_id = base64.urlsafe_b64decode(state.encode()).decode()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    try:
        user_db = UserDB()
        user = user_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if setup_action in ("install", "update"):
            user_db.link_github_installation(user_id, installation_id)
            logging.info("Linked installation %s to user %s (action=%s)", installation_id, user_id, setup_action)

            try:
                token = await installation_token_for_id(installation_id)
                async with httpx.AsyncClient(timeout=10) as hx:
                    resp = await hx.get(
                        "https://api.github.com/user",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                        },
                    )
                if resp.is_success:
                    gh_data = resp.json()
                    GithubUserDB().upsert(GithubUser(
                        github_user_id=gh_data["id"],
                        login=gh_data.get("login", ""),
                        name=gh_data.get("name"),
                        avatar_url=gh_data.get("avatar_url"),
                        installation_id=installation_id,
                        user_id=user_id,
                    ))
                    user_db.link_github_installation(user_id, installation_id, github_user_id=gh_data["id"])
            except Exception as gh_err:
                logging.warning("Could not fetch GitHub user info: %s", gh_err)

        return HTMLResponse(content=_render_install_status_page(user_id, state))

    except HTTPException:
        raise
    except Exception as e:
        logging.error("Error processing GitHub callback: %s", e)
        raise HTTPException(status_code=500, detail="Unable to process GitHub callback")


@router.post("/webhook")
async def webhook_handler(request: Request):
    try:
        body = await request.json()

        if "installation" not in body or "action" not in body:
            return {"status": "success", "message": "Webhook processed (no installation event)"}

        installation_id = body["installation"]["id"]
        action = body["action"]

        user_db = UserDB()
        user = user_db.get_user_by_installation_id(installation_id)
        if not user:
            logging.error("No user found for installation_id %s", installation_id)
            raise HTTPException(status_code=404, detail="User not found for this installation")

        user_id = user.user_id
        logging.info("Webhook: action=%s installation=%s user=%s", action, installation_id, user_id)

        if action == "deleted":
            user_db.remove_installation(installation_id)
            return {"status": "success", "message": "Installation removed"}

        if action not in ("created", "added"):
            return {"status": "success", "message": f"Unhandled action: {action}"}

        repositories_key = "repositories" if action == "created" else "repositories_added"
        repositories = body.get(repositories_key, [])

        if not repositories:
            return {"status": "warning", "message": "No repositories in webhook body"}

        try:
            await installation_token_for_id(installation_id)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to get GitHub installation token")

        user_repositories_db = UserRepositoryDB()
        created_repos = []
        for repo_data in repositories:
            repo_name = repo_data.get("full_name", repo_data.get("name", ""))
            if not repo_name:
                continue
            if user_repositories_db.find_user_repository(user_id, repo_name):
                continue
            repo = UserRepository(
                repository_name=repo_name,
                user_id=user_id,
                action=action,
                is_indexed=False,
                indexing_status="pending",
            )
            user_repositories_db.add_user_repository(repo)
            created_repos.append(repo)
            logging.info("Added repository %s for user %s", repo_name, user_id)

        scheduler_status = "no_repos"
        if created_repos:
            from sdk.indexer import indexing_scheduler, progress

            progress.ensure_event_for_user(user_id, [r.repository_name for r in created_repos])

            async def token_provider(_user_id: str) -> str:
                return await installation_token_for_id(str(installation_id))

            try:
                result = await indexing_scheduler.trigger(
                    user_id=user_id,
                    repository_names=[r.repository_name for r in created_repos],
                    token_provider=token_provider,
                    trigger="webhook",
                    bulk_limit=True,
                )
                scheduler_status = result["status"]
            except Exception as e:
                logging.warning("Could not schedule indexing for user %s: %s", user_id, e)

        return {
            "status": "success",
            "message": f"Processed {len(created_repos)} new repositories",
            "created_repositories": [r.repository_name for r in created_repos],
            "indexing_status": scheduler_status,
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error("Webhook error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Unable to process webhook")
