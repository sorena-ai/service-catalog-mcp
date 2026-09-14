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
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Service Catalog — Indexing repositories</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 72px auto; padding: 0 24px; color: #111; }}
    h1 {{ font-size: 28px; margin: 0 0 12px; }}
    p {{ color: #555; line-height: 1.5; margin: 0 0 24px; }}
    .phases {{ list-style: none; padding: 0; margin: 0 0 28px; }}
    .phases li {{ display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 15px; color: #999; }}
    .phases li.active {{ color: #111; font-weight: 600; }}
    .phases li.done {{ color: #555; }}
    .phases li.failed {{ color: #c0392b; }}
    .check {{ width: 18px; text-align: center; flex-shrink: 0; }}
    .repos {{ border: 1px solid #e5e5e5; border-radius: 12px; overflow: hidden; }}
    .repo {{ display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
    .repo:last-child {{ border-bottom: none; }}
    .repo-name {{ flex: 1; font-weight: 500; }}
    .repo-step {{ color: #888; font-size: 13px; }}
    .repo-error {{ color: #c0392b; font-size: 13px; }}
    .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
    .dot-pending {{ background: #ddd; }}
    .dot-in_progress {{ background: #3b82f6; animation: pulse 1.2s ease-in-out infinite; }}
    .dot-done {{ background: #22c55e; }}
    .dot-failed {{ background: #ef4444; }}
    .spinner {{ display: inline-block; width: 14px; height: 14px; border: 2px solid #ddd; border-top-color: #3b82f6; border-radius: 50%; animation: spin 0.9s linear infinite; flex-shrink: 0; }}
    .done-banner {{ background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 16px 20px; color: #166534; font-weight: 500; margin-bottom: 24px; }}
    .fail-banner {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 12px; padding: 16px 20px; color: #991b1b; font-weight: 500; margin-bottom: 24px; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  </style>
</head>
<body>
  <h1>Connected to GitHub ✓</h1>
  <p>Your repositories are being indexed. This takes a few minutes — you can start using Service Catalog in Claude Desktop once it's done.</p>
  <div id="banner"></div>
  <ul class="phases" id="phases"></ul>
  <div class="repos" id="repos" style="display:none"></div>
  <script>
    const STATE = {state!r};
    const PHASES = [
      {{ id: "starting",              label: "Queued" }},
      {{ id: "waiting_for_repos",     label: "Queued" }},
      {{ id: "cloning",               label: "Cloning repositories" }},
      {{ id: "analyzing_codebase",    label: "Analyzing codebase" }},
      {{ id: "scanning",              label: "Scanning repositories" }},
      {{ id: "generating_repo_context", label: "Generating context" }},
      {{ id: "building_edges",        label: "Building relationships" }},
      {{ id: "done",                  label: "Done" }},
      {{ id: "failed",                label: "Failed" }},
    ];
    const PHASE_ORDER = ["starting","waiting_for_repos","cloning","analyzing_codebase","scanning","generating_repo_context","building_edges","done","failed"];

    function phaseIndex(id) {{ return PHASE_ORDER.indexOf(id); }}

    function renderPhases(currentPhase) {{
      const el = document.getElementById("phases");
      const cur = phaseIndex(currentPhase);
      const isFailed = currentPhase === "failed";
      const isDone = currentPhase === "done";
      const visible = PHASES.filter(p => !["starting","waiting_for_repos","failed"].includes(p.id));
      el.innerHTML = visible.map(p => {{
        const idx = phaseIndex(p.id);
        const isDonePhase = p.id === "done";
        let cls = "", icon = "";
        if (isFailed) {{
          cls = idx < cur ? "done" : "";
          icon = idx < cur ? "✓" : "·";
        }} else if (isDonePhase && isDone) {{
          cls = "done"; icon = "✓";
        }} else if (idx < cur && !isDonePhase) {{
          cls = "done"; icon = "✓";
        }} else if (idx === cur) {{
          cls = "active"; icon = '<span class="spinner"></span>';
        }} else {{
          icon = "·";
        }}
        return `<li class="${{cls}}"><span class="check">${{icon}}</span>${{p.label}}</li>`;
      }}).join("");
    }}

    function renderRepos(repos) {{
      if (!repos || repos.length === 0) return;
      const el = document.getElementById("repos");
      el.style.display = "";
      el.innerHTML = repos.map(r => {{
        const detail = r.status === "failed"
          ? `<span class="repo-error">${{r.error_message || "failed"}}</span>`
          : r.step ? `<span class="repo-step">${{r.step}}</span>` : "";
        return `<div class="repo">
          <div class="dot dot-${{r.status}}"></div>
          <div class="repo-name">${{r.name}}</div>
          ${{detail}}
        </div>`;
      }}).join("");
    }}

    function renderBanner(phase) {{
      const el = document.getElementById("banner");
      if (phase === "done") {{
        el.innerHTML = '<div class="done-banner">All repositories indexed — you can now use Service Catalog in Claude Desktop.</div>';
      }} else if (phase === "failed") {{
        el.innerHTML = '<div class="fail-banner">Indexing encountered errors. Some repositories may be unavailable.</div>';
      }} else {{
        el.innerHTML = "";
      }}
    }}

    async function poll() {{
      try {{
        const res = await fetch("/indexing/status?state=" + encodeURIComponent(STATE));
        if (!res.ok) return;
        const data = await res.json();
        renderPhases(data.phase);
        renderRepos(data.repos);
        renderBanner(data.phase);
        if (data.phase !== "done" && data.phase !== "failed") {{
          setTimeout(poll, 1500);
        }}
      }} catch (e) {{
        setTimeout(poll, 3000);
      }}
    }}

    renderPhases("starting");
    poll();
  </script>
</body>
</html>"""


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
            from sdk.indexer import progress

            progress.ensure_event_for_user(user_id, [r.repository_name for r in created_repos])

            async def token_provider(_user_id: str) -> str:
                return await installation_token_for_id(str(installation_id))

            try:
                result = await request.app.state.scheduler.trigger(
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
