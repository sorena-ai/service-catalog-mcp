"""Repository pass context generator.

Runs a single Claude CLI pass over the cloned workspace to produce
per-repo ``RepositoryContext`` rows. Codebase pass output is fed in as grounding
material; deterministic facts are summarized into a compact input JSON so
the prompt does not balloon.

Called by the event orchestrator after the codebase pass has completed and
deterministic scanners have written their rows.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, List, Optional

from lib.cli import get_cli
from lib.cli.base import CliRunConfig

try:
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover
    def _traceable(*args, **kwargs):
        def _decorator(fn):
            return fn

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

from sdk.indexer.clone_workspace import IndexCloneWorkspace
from sdk.indexer.db.codebase_contexts import CodebaseContext
from sdk.indexer.db.contexts import RepositoryContext, RepositoryContextDB
from sdk.indexer.db.dependencies import RepositoryDependencyDB
from sdk.indexer.db.extractions import RepositoryExtractionDB
from sdk.indexer.db.files import RepositoryFileDB
from sdk.indexer.db.languages import RepositoryLanguageDB
from sdk.indexer.db.tree import RepositoryTreeDB
from sdk.indexer.db.workspaces import RepositoryWorkspaceDB
from sdk.indexer.prompts.repo_analyzer import (
    INPUT_FILENAME,
    OUTPUT_FILENAME,
    REPO_PROMPT,
)
from sdk import vocabulary as vocab_mod

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 1800
TOP_DEPENDENCY_COUNT = 30


class RepoParseError(RuntimeError):
    pass


@_traceable(run_type="chain", name="indexer.repo_analysis")
def run_repo_analysis(
    workspace: IndexCloneWorkspace,
    event_id: str,
    repository_names: Iterable[str],
    codebase_contexts: Iterable[CodebaseContext] = (),
    model: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> dict[str, int]:
    """Generate per-repo contexts for ``repository_names``.

    Returns a ``{repository_name: row_count}`` map. Raises on parse error
    or Claude failure; deterministic facts in Mongo remain intact.
    """
    user_id = workspace.user_id
    event_dir = workspace.prepare(event_id)

    repo_list = list(repository_names)
    if not repo_list:
        logger.info("Repository pass invoked with no repositories; skipping.")
        return {}

    _assemble_input(event_dir, user_id, repo_list, list(codebase_contexts))

    cli = get_cli()
    config = CliRunConfig(
        cwd=event_dir,
        prompt=REPO_PROMPT,
        model=model or os.getenv("CLAUDE_CLI_DEFAULT_MODEL") or DEFAULT_MODEL,
        max_turns=200,
        timeout=timeout_seconds,
    )
    result = cli.run(config)

    rows_by_repo = _parse_output(event_dir / OUTPUT_FILENAME, user_id, repo_list)
    counts = _persist(rows_by_repo)
    logger.info(
        "Repository pass completed for user=%s event=%s repos=%d cost_usd=%s",
        user_id, event_id, len(counts), result.cost_usd,
    )
    return counts


# -- input assembly --------------------------------------------------------

def _assemble_input(
    event_dir: Path,
    user_id: str,
    repository_names: List[str],
    codebase_contexts: List[CodebaseContext],
) -> Path:
    payload = {
        "user_id": user_id,
        "vocab": _vocab_dict(),
        "codebase_contexts": [
            {"context_type": c.context_type, "content": c.content}
            for c in codebase_contexts
        ],
        "repos": [_repo_card(user_id, name) for name in repository_names],
    }
    out = event_dir / INPUT_FILENAME
    out.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    logger.info(
        "Wrote repository pass input %s (repos=%d, codebase_contexts=%d)",
        out, len(payload["repos"]), len(payload["codebase_contexts"]),
    )
    return out


def _repo_card(user_id: str, name: str) -> dict:
    lang_db = RepositoryLanguageDB()
    ws_db = RepositoryWorkspaceDB()
    file_db = RepositoryFileDB()
    tree_db = RepositoryTreeDB()
    dep_db = RepositoryDependencyDB()
    ext_db = RepositoryExtractionDB()

    languages = [
        {"language": lang.language, "confidence": lang.confidence}
        for lang in lang_db.find_for_repository(user_id, name)
    ]
    workspaces = [
        {
            "workspace_path": w.workspace_path,
            "manifest_files": w.manifest_files,
            "detected_language": w.detected_language,
            "detected_package_manager": w.detected_package_manager,
        }
        for w in ws_db.find_for_repository(user_id, name)
    ]
    files = [
        {"path": f.path, "role": f.role, "language": f.language}
        for f in file_db.find_for_repository(user_id, name)
    ]
    file_role_counts: Counter = Counter(f["role"] for f in files)

    tree = tree_db.get(user_id, name)
    deps = dep_db.find_for_repository(user_id, name)
    deps.sort(key=lambda d: (d.dependency_group != "runtime", d.package_manager, d.name_normalized))
    top_deps = [
        {
            "package_manager": d.package_manager,
            "name": d.name,
            "version": d.version_constraint,
            "group": d.dependency_group,
        }
        for d in deps[:TOP_DEPENDENCY_COUNT]
    ]

    extractions_by_type: dict[str, List[dict]] = defaultdict(list)
    for ext in ext_db.find_for_repository(user_id, name):
        extractions_by_type[ext.extraction_type].append(ext.data)

    return {
        "name": name,
        "dir": name.replace("/", "__"),
        "facts": {
            "languages": languages,
            "workspaces": workspaces,
            "file_role_counts": dict(file_role_counts),
            "files": files,
            "tree_path_count": tree.file_count if tree else 0,
            "tree_depth_max": tree.depth_max if tree else 0,
            "dependencies_top": top_deps,
            "dependency_total": len(deps),
            "extractions": dict(extractions_by_type),
        },
    }


def _vocab_dict() -> dict:
    return {
        "languages": vocab_mod.LANGUAGES,
        "frameworks": vocab_mod.FRAMEWORKS,
        "platforms": vocab_mod.PLATFORMS,
        "runtimes": vocab_mod.RUNTIMES,
        "package_managers": vocab_mod.PACKAGE_MANAGERS,
        "repo_context_types": vocab_mod.REPO_CONTEXT_TYPES,
        "edge_types": vocab_mod.EDGE_TYPES,
    }


# -- output parsing --------------------------------------------------------

def _parse_output(
    output_path: Path, user_id: str, expected_names: List[str]
) -> dict[str, List[RepositoryContext]]:
    if not output_path.exists():
        raise RepoParseError(f"Repository pass output missing: {output_path}")

    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RepoParseError(f"Invalid JSON in {output_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RepoParseError(f"Repository pass output must be a JSON object, got {type(data).__name__}")
    repos_data = data.get("repos")
    if not isinstance(repos_data, list):
        raise RepoParseError("Repository pass output missing required 'repos' list")

    expected = set(expected_names)
    out: dict[str, List[RepositoryContext]] = {}
    for entry in repos_data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or name not in expected:
            logger.warning("Repository pass ignored unknown repo entry: %r", name)
            continue
        contexts = entry.get("contexts")
        if not isinstance(contexts, list):
            raise RepoParseError(f"repo {name}: 'contexts' must be a list")

        rows = _build_rows(user_id, name, contexts)
        if not any(r.context_type == "repo_summary" for r in rows):
            raise RepoParseError(f"repo {name} missing required repo_summary context")
        out[name] = rows

    missing = expected - out.keys()
    if missing:
        raise RepoParseError(f"Repository pass output missing repos: {sorted(missing)}")
    return out


def _build_rows(
    user_id: str, repository_name: str, contexts: List[dict]
) -> List[RepositoryContext]:
    valid_types = set(vocab_mod.REPO_CONTEXT_TYPES)
    rows: List[RepositoryContext] = []
    for c in contexts:
        if not isinstance(c, dict):
            continue
        ctype = c.get("context_type")
        content = c.get("content")
        if ctype not in valid_types:
            logger.warning(
                "repo %s: skipping unknown context_type %r", repository_name, ctype
            )
            continue
        if not isinstance(content, str) or not content.strip():
            logger.warning(
                "repo %s: skipping empty content for %s", repository_name, ctype
            )
            continue
        rows.append(
            RepositoryContext(
                user_id=user_id,
                repository_name=repository_name,
                context_type=ctype,
                content=content.strip(),
                workspace_path=c.get("workspace_path") or None,
                tags=_string_list(c.get("tags")),
                paths=_string_list(c.get("paths")),
                symbols=_string_list(c.get("symbols")),
                referenced_fact_ids=_string_list(c.get("referenced_fact_ids")),
            )
        )
    return rows


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value if isinstance(x, (str, int))]


# -- persistence -----------------------------------------------------------

def _persist(rows_by_repo: dict[str, List[RepositoryContext]]) -> dict[str, int]:
    db = RepositoryContextDB()
    counts: dict[str, int] = {}
    for repo, rows in rows_by_repo.items():
        first = rows[0] if rows else None
        if first is None:
            counts[repo] = 0
            continue
        db.replace_for_repository(first.user_id, repo, rows)
        counts[repo] = len(rows)
    return counts


__all__ = ["run_repo_analysis", "RepoParseError"]
