"""Codebase-pass input assembler.

Builds the ``__codebase_input.json`` file that Claude reads at the start
of a codebase pass run. Existing-repo cards summarize the facts already stored
for each indexed repo; new-repo entries point Claude at directories it
should inspect on disk.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from sdk.indexer.db.contexts import RepositoryContextDB
from sdk.indexer.db.dependencies import RepositoryDependencyDB
from sdk.indexer.db.extractions import RepositoryExtractionDB
from sdk.indexer.db.languages import RepositoryLanguageDB
from sdk import vocabulary as vocab_mod
from sdk.indexer.prompts.workspace_analyzer import INPUT_FILENAME

logger = logging.getLogger(__name__)


@dataclass
class ExistingRepoCard:
    name: str
    languages: List[dict] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    platforms: List[str] = field(default_factory=list)
    top_dependencies: List[dict] = field(default_factory=list)
    repo_summary_snippet: Optional[str] = None


@dataclass
class NewRepoEntry:
    name: str
    dir: str  # event-dir-relative, flattened safe name (e.g. ``org__name``)


def assemble_input(
    event_dir: Path,
    user_id: str,
    existing_repos: Iterable[ExistingRepoCard],
    new_repos: Iterable[NewRepoEntry],
) -> Path:
    payload = {
        "user_id": user_id,
        "vocab": _vocab_dict(),
        "existing_repos": [_card_to_dict(c) for c in existing_repos],
        "new_repos": [{"name": r.name, "dir": r.dir} for r in new_repos],
    }
    out = event_dir / INPUT_FILENAME
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info(
        "Wrote codebase pass input %s (existing=%d, new=%d)",
        out,
        len(payload["existing_repos"]),
        len(payload["new_repos"]),
    )
    return out


def load_existing_repo_cards(
    user_id: str, repository_names: Iterable[str], top_dependency_count: int = 15
) -> List[ExistingRepoCard]:
    """Build cards from the Mongo facts collections for already-indexed repos."""
    lang_db = RepositoryLanguageDB()
    dep_db = RepositoryDependencyDB()
    ext_db = RepositoryExtractionDB()
    ctx_db = RepositoryContextDB()

    cards: List[ExistingRepoCard] = []
    for name in repository_names:
        languages = [
            {"language": lang.language, "confidence": lang.confidence}
            for lang in lang_db.find_for_repository(user_id, name)
        ]
        deps = dep_db.find_for_repository(user_id, name)
        deps = sorted(deps, key=lambda d: d.dependency_group != "runtime")
        top_deps = [
            {
                "package_manager": d.package_manager,
                "name": d.name,
                "version": d.version_constraint,
            }
            for d in deps[:top_dependency_count]
        ]
        frameworks = sorted(
            {
                e.data.get("framework")
                for e in ext_db.find_for_repository(user_id, name, "framework")
                if e.data.get("framework")
            }
        )
        platforms = sorted(
            {
                e.data.get("platform")
                for e in ext_db.find_for_repository(user_id, name, "platform")
                if e.data.get("platform")
            }
        )
        snippet = None
        for ctx in ctx_db.find_for_repository(user_id, name, ["repo_summary"]):
            snippet = (ctx.content or "").strip()[:1000]
            break

        cards.append(
            ExistingRepoCard(
                name=name,
                languages=languages,
                frameworks=frameworks,
                platforms=platforms,
                top_dependencies=top_deps,
                repo_summary_snippet=snippet,
            )
        )
    return cards


def _card_to_dict(card: ExistingRepoCard) -> dict:
    return {
        "name": card.name,
        "languages": card.languages,
        "frameworks": card.frameworks,
        "platforms": card.platforms,
        "top_dependencies": card.top_dependencies,
        "repo_summary_snippet": card.repo_summary_snippet,
    }


def _vocab_dict() -> dict:
    return {
        "repo_classes": vocab_mod.REPO_CLASSES,
        "languages": vocab_mod.LANGUAGES,
        "frameworks": vocab_mod.FRAMEWORKS,
        "platforms": vocab_mod.PLATFORMS,
        "runtimes": vocab_mod.RUNTIMES,
        "package_managers": vocab_mod.PACKAGE_MANAGERS,
        "codebase_context_types": vocab_mod.CODEBASE_CONTEXT_TYPES,
        "edge_types": vocab_mod.EDGE_TYPES,
    }
