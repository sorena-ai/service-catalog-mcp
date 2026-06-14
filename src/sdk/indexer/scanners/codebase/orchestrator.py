"""Codebase-pass orchestrator.

Glues input assembly, Claude CLI invocation, output parsing, and
persistence into a single ``run_tier1`` entry point. The caller (the
event-level orchestrator) is responsible for cloning repos and
preparing the workspace before calling here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Iterable, List

from lib.claude_cli.client import ClaudeCLIClient
from lib.claude_cli.models import ClaudeRunConfig

try:
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover
    def _traceable(*args, **kwargs):
        def _decorator(fn):
            return fn

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

from ...clone_workspace import IndexCloneWorkspace
from ...db.codebase_contexts import CodebaseContextDB
from ...db.codebase_runs import CodebaseRun, CodebaseRunDB
from ...prompts.tier1_codebase import (
    OUTPUT_FILENAME,
    TIER1_PROMPT,
)
from .assembler import (
    ExistingRepoCard,
    NewRepoEntry,
    assemble_input,
    load_existing_repo_cards,
)
from .parser import Tier1ParseError, parse_output

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 1800


@_traceable(run_type="chain", name="indexer.tier1")
def run_tier1(
    workspace: IndexCloneWorkspace,
    event_id: str,
    new_repos: Iterable[NewRepoEntry],
    existing_repos: Iterable[ExistingRepoCard] = (),
    trigger: str = "auto",
    model: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> CodebaseRun:
    user_id = workspace.user_id
    event_dir = workspace.prepare(event_id)

    new_list: List[NewRepoEntry] = list(new_repos)
    existing_list: List[ExistingRepoCard] = list(existing_repos)

    runs_db = CodebaseRunDB()
    run = CodebaseRun(
        user_id=user_id,
        status="running",
        trigger=trigger,
        input_repository_names=[r.name for r in new_list],
        clone_dir=str(event_dir),
        model_version=model or os.getenv("CLAUDE_CLI_DEFAULT_MODEL") or DEFAULT_MODEL,
        started_at=datetime.utcnow(),
    )
    run_id = runs_db.insert(run)

    try:
        assemble_input(event_dir, user_id, existing_list, new_list)

        client = ClaudeCLIClient()
        config = ClaudeRunConfig(
            cwd=str(event_dir),
            prompt=TIER1_PROMPT,
            model=model or os.getenv("CLAUDE_CLI_DEFAULT_MODEL") or DEFAULT_MODEL,
            max_turns=100,
            timeout=timeout_seconds,
        )
        result = client.run(config)

        rows = parse_output(event_dir / OUTPUT_FILENAME, user_id)

        ctx_db = CodebaseContextDB()
        for row in rows:
            ctx_db.upsert(row)

        runs_db.update(
            run_id,
            {
                "status": "completed",
                "completed_at": datetime.utcnow(),
                "cost_usd": result.cost_usd,
            },
        )
        run.status = "completed"
        run.cost_usd = result.cost_usd
        run.completed_at = datetime.utcnow()
        logger.info(
            "Codebase pass completed for user=%s event=%s (cost_usd=%s, rows=%d)",
            user_id, event_id, result.cost_usd, len(rows),
        )
        return run

    except Tier1ParseError as exc:
        runs_db.update(
            run_id,
            {
                "status": "failed",
                "completed_at": datetime.utcnow(),
                "error_message": f"parse_error: {exc}",
            },
        )
        logger.exception("Codebase pass parse failed for user=%s event=%s", user_id, event_id)
        raise
    except Exception as exc:
        runs_db.update(
            run_id,
            {
                "status": "failed",
                "completed_at": datetime.utcnow(),
                "error_message": str(exc),
            },
        )
        logger.exception("Codebase pass run failed for user=%s event=%s", user_id, event_id)
        raise


__all__ = [
    "run_tier1",
    "ExistingRepoCard",
    "NewRepoEntry",
    "load_existing_repo_cards",
]
