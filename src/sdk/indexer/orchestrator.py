"""Event-level indexing orchestrator.

One indexing event covers N repositories for a single scope. Pipeline:

  1. Insert ``IndexEventRun`` (status=running)
  2. Resolve a fresh GitHub token (token providers are async)
  3. Prepare the per-event clone workspace
  4. Clone every repo in this event
  5. Codebase pass (Claude CLI)
  6. Per-repo deterministic + extraction scanners
  7. Repository pass — repo context generator (Claude CLI)
  8. Build cross-repo edges from facts
  9. Mark ``user_repositories`` as indexed
  10. Cleanup workspace; finalize ``IndexEventRun``

Codebase pass / repository pass failures fail the whole event. Per-repo scanner errors
are logged and skipped — other repos continue.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, List

from sdk.storage.db.mongo.repositories import UserRepositoryDB

try:
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover
    def _traceable(*args, **kwargs):
        def _decorator(fn):
            return fn

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

from sdk.workspace import Workspace
from . import progress
from .db.codebase_contexts import CodebaseContextDB
from .db.dependencies import RepositoryDependencyDB
from .db.extractions import RepositoryExtractionDB
from .db.files import RepositoryFileDB
from .db.languages import RepositoryLanguageDB
from .db.runs import IndexEventRun, IndexEventRunDB
from .db.tree import RepositoryTreeDB
from .db.workspaces import RepositoryWorkspaceDB
from .relationships import build_edges, persist_edges
from .workspace_analyzer import (
    NewRepoEntry,
    load_existing_repo_cards,
    run_workspace_analysis,
)
from .workspace_analyzer.scanners import (
    scan_languages,
    scan_tree,
    scan_workspaces,
)
from .repo_analyzer import run_repo_analysis
from .repo_analyzer.scanners import (
    scan_dependencies,
    scan_files,
)
from .repo_analyzer.scanners.extractions import (
    scan_chef,
    scan_docker,
    scan_frameworks,
    scan_github_actions,
    scan_helm,
    scan_kubernetes,
    scan_platforms_from_tree,
    scan_terraform,
)

logger = logging.getLogger(__name__)

TokenProvider = Callable[[str], Awaitable[str]]
@_traceable(run_type="chain", name="indexer.run_indexing_event")
async def run_indexing_event(
    user_id: str,
    repository_names: List[str],
    token_provider: TokenProvider,
    trigger: str = "auto",
    *,
    workspace: Workspace,
) -> str:
    """Run one indexing event end-to-end. Returns the ``IndexEventRun`` id."""
    if not repository_names:
        raise ValueError("repository_names cannot be empty")

    event_id = str(uuid.uuid4())
    runs_db = IndexEventRunDB()

    run = IndexEventRun(
        user_id=user_id,
        status="running",
        trigger=trigger,
        input_repository_names=list(repository_names),
        clone_dir=str(workspace.scope_dir(user_id, event_id)),
        started_at=datetime.utcnow(),
    )
    run_id = runs_db.insert(run)
    progress.begin_event(user_id, event_id, repository_names)

    try:
        token = await token_provider(user_id)

        # 1. Clone all repos for this event.
        progress.set_phase(user_id, "cloning")
        new_entries: List[NewRepoEntry] = []

        async def _clone_repo(repo: str):
            await workspace.clone(user_id, event_id, repo, token, resume=False)
            new_entries.append(NewRepoEntry(name=repo, dir=repo.replace("/", "__")))
            
        await asyncio.gather(*(_clone_repo(repo) for repo in repository_names))

        # 2. Codebase pass — uses cached cards for already-indexed repos.
        progress.set_phase(user_id, "analyzing_codebase")
        existing_names = await asyncio.to_thread(
            _existing_indexed_names, user_id, set(repository_names)
        )
        existing_cards = await asyncio.to_thread(
            load_existing_repo_cards, user_id, existing_names
        )
        codebase_run = await asyncio.to_thread(
            run_workspace_analysis,
            user_id,
            workspace,
            event_id,
            new_entries,
            existing_cards,
            trigger,
        )
        runs_db.update(run_id, {"codebase_run_id": str(codebase_run._id)})

        # 3. Per-repo deterministic + extraction scanners.
        progress.set_phase(user_id, "scanning")
        repo_db = UserRepositoryDB()
        scanned_repositories: List[str] = []
        
        async def _scan_repo(repo: str):
            try:
                await asyncio.to_thread(
                    repo_db.update_indexed_status, user_id, repo, False, "indexing"
                )
                await asyncio.to_thread(
                    _scan_and_persist_one,
                    user_id,
                    repo,
                    workspace.repo_dir(user_id, event_id, repo),
                )
                progress.mark_repo_done(user_id, repo)
                scanned_repositories.append(repo)
            except Exception as exc:
                logger.exception("Scanner failed for %s; skipping repo", repo)
                progress.mark_repo_failed(user_id, repo, str(exc))
                await asyncio.to_thread(
                    repo_db.update_indexed_status, user_id, repo, False, "failed"
                )

        await asyncio.gather(*(_scan_repo(repo) for repo in repository_names))

        if scanned_repositories:
            # 4. Repository pass — runs once for all repos with codebase contexts as grounding.
            progress.set_phase(user_id, "generating_repo_context")
            codebase_contexts = await asyncio.to_thread(
                CodebaseContextDB().find_for_user, user_id
            )
            await asyncio.to_thread(
                run_repo_analysis,
                user_id,
                workspace,
                event_id,
                scanned_repositories,
                codebase_contexts,
            )

            # 5. Edges — must run after every repo's facts exist.
            progress.set_phase(user_id, "building_edges")
            edges = await asyncio.to_thread(build_edges, user_id, scanned_repositories)
            await asyncio.to_thread(persist_edges, user_id, scanned_repositories, edges)

            # 6. Mark repos as indexed in user_repositories + per-repo SSE.
            for repo in scanned_repositories:
                await asyncio.to_thread(
                    repo_db.update_indexed_status, user_id, repo, True, "indexed"
                )

        runs_db.update(
            run_id,
            {"status": "completed", "completed_at": datetime.utcnow()},
        )
        progress.complete_event(user_id)
        logger.info(
            "Indexing event completed: user=%s event=%s repos=%d",
            user_id, event_id, len(repository_names),
        )
        return run_id

    except Exception as exc:
        runs_db.update(
            run_id,
            {
                "status": "failed",
                "completed_at": datetime.utcnow(),
                "error_message": str(exc),
            },
        )
        progress.fail_event(user_id, str(exc))
        logger.exception("Indexing event failed: user=%s event=%s", user_id, event_id)
        raise
    finally:
        try:
            await asyncio.to_thread(workspace.wipe_scope, user_id, event_id)
        except Exception:
            logger.exception("Workspace cleanup failed: event=%s", event_id)
# -- helpers --------------------------------------------------------------

def _existing_indexed_names(user_id: str, exclude: set[str]) -> List[str]:
    indexed = UserRepositoryDB().find_user_indexed_repositories(user_id)
    return [r.repository_name for r in indexed if r.repository_name not in exclude]
def _scan_and_persist_one(user_id: str, repository_name: str, repo_dir: Path) -> None:
    """Run all deterministic and extraction scanners for ``repository_name``
    and persist results into the per-dimension and generic collections."""
    from ._walker import walk_repo
    files = list(walk_repo(repo_dir))

    progress.set_repo_step(user_id, repository_name, "Mapping file tree")
    tree = scan_tree(files, user_id, repository_name)
    RepositoryTreeDB().upsert(tree)

    paths = list(tree.paths or [])

    progress.set_repo_step(user_id, repository_name, "Detecting languages")
    languages = scan_languages(files, user_id, repository_name)
    RepositoryLanguageDB().replace_for_repository(user_id, repository_name, languages)

    progress.set_repo_step(user_id, repository_name, "Curating important files")
    curated_files = scan_files(files, user_id, repository_name)
    RepositoryFileDB().replace_for_repository(user_id, repository_name, curated_files)

    progress.set_repo_step(user_id, repository_name, "Finding workspaces")
    workspaces = scan_workspaces(files, repo_dir, user_id, repository_name)
    RepositoryWorkspaceDB().replace_for_repository(user_id, repository_name, workspaces)

    progress.set_repo_step(user_id, repository_name, "Reading dependencies")
    deps = scan_dependencies(repo_dir, user_id, repository_name, workspaces)
    RepositoryDependencyDB().replace_for_repository(user_id, repository_name, deps)

    extractions: list = []

    if _has_docker(paths):
        progress.set_repo_step(user_id, repository_name, "Examining Dockerfiles")
        extractions.extend(scan_docker(files, repo_dir, user_id, repository_name))
    if _has_github_actions(paths):
        progress.set_repo_step(user_id, repository_name, "Examining GitHub Actions")
        extractions.extend(scan_github_actions(files, repo_dir, user_id, repository_name))
    if _has_helm(paths):
        progress.set_repo_step(user_id, repository_name, "Examining Helm charts")
        extractions.extend(scan_helm(files, repo_dir, user_id, repository_name))
    if _has_chef(paths):
        progress.set_repo_step(user_id, repository_name, "Examining Chef cookbooks")
        extractions.extend(scan_chef(files, repo_dir, user_id, repository_name))
    if _has_terraform(paths):
        progress.set_repo_step(user_id, repository_name, "Examining Terraform modules")
        extractions.extend(scan_terraform(files, repo_dir, user_id, repository_name))

    kubernetes = scan_kubernetes(files, repo_dir, user_id, repository_name) if _has_yaml(paths) else []
    if kubernetes:
        progress.set_repo_step(user_id, repository_name, "Examining Kubernetes manifests")
        extractions.extend(kubernetes)

    frameworks = scan_frameworks(deps, user_id, repository_name)
    if frameworks:
        progress.set_repo_step(user_id, repository_name, "Detecting frameworks")
        extractions.extend(frameworks)

    # Platforms layer over the rest.
    platforms = scan_platforms_from_tree(tree, extractions=extractions)
    if platforms:
        progress.set_repo_step(user_id, repository_name, "Detecting platforms")
        extractions.extend(platforms)

    ext_db = RepositoryExtractionDB()
    ext_db.delete_for_repository(user_id, repository_name)
    grouped: Dict[str, list] = defaultdict(list)
    for e in extractions:
        grouped[e.extraction_type].append(e)
    for etype, rows in grouped.items():
        ext_db.replace_for_repository_type(user_id, repository_name, etype, rows)
def _has_docker(paths: List[str]) -> bool:
    return any(
        path.rsplit("/", 1)[-1] == "Dockerfile"
        or path.rsplit("/", 1)[-1].startswith("Dockerfile.")
        or path.rsplit("/", 1)[-1].startswith("docker-compose")
        and path.endswith((".yml", ".yaml"))
        for path in paths
    )
def _has_github_actions(paths: List[str]) -> bool:
    return any(
        path.startswith(".github/workflows/")
        and path.endswith((".yml", ".yaml"))
        for path in paths
    )
def _has_helm(paths: List[str]) -> bool:
    return any(path.rsplit("/", 1)[-1] == "Chart.yaml" for path in paths)
def _has_chef(paths: List[str]) -> bool:
    return any(
        path.rsplit("/", 1)[-1] in {"metadata.rb", "Berksfile", "Policyfile.rb"}
        for path in paths
    )
def _has_terraform(paths: List[str]) -> bool:
    return any(path.endswith(".tf") or path.endswith(".tf.json") for path in paths)
def _has_yaml(paths: List[str]) -> bool:
    return any(
        path.endswith((".yml", ".yaml"))
        and not path.startswith(".github/workflows/")
        for path in paths
    )
__all__ = ["run_indexing_event"]
