"""Natural-language query resolver for ``query_user_codebase``.

Translates a user's NL query into a ``PublicSearchFilters`` shape plus a
short keyword list for context text search. The resolver is grounded
against the user's ``codebase_contexts`` (``codebase_terminology`` and
``query_refinement_hints``) so domain-specific phrasing maps to the
controlled vocabulary correctly.

Output is strictly validated against the ``PublicSearchFilters`` shape;
invalid JSON or unknown fields raise so the caller can return HTTP 400.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional, Tuple

from pydantic import BaseModel, ValidationError

from lib.tracing import traced_anthropic_client

from sdk import vocabulary as vocab_mod
from ..indexer.db.codebase_contexts import CodebaseContextDB
from .filters import (
    PUBLIC_HAS_FILE_WHITELIST,
    PUBLIC_WORKSPACE_MANIFEST_WHITELIST,
    PublicSearchFilters,
)

try:
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover
    def _traceable(*args, **kwargs):
        def _decorator(fn):
            return fn

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_KEYWORDS = 5


class NLResolverError(RuntimeError):
    pass


class _ResolverOutput(BaseModel):
    filters: PublicSearchFilters
    context_keywords: List[str] = []


@_traceable(run_type="chain", name="nl_resolver.resolve")
def resolve_nl_query(
    user_id: str, nl_query: str, model: Optional[str] = None
) -> Tuple[PublicSearchFilters, List[str]]:
    """Return (filters, keywords). Raises NLResolverError on any failure."""
    if not nl_query or not nl_query.strip():
        raise NLResolverError("nl_query is required")

    grounding = _load_grounding(user_id)
    prompt = _build_prompt(nl_query, grounding)

    try:
        client = traced_anthropic_client()
    except ImportError as exc:
        raise NLResolverError("anthropic SDK not installed") from exc

    try:
        message = client.messages.create(
            model=model or os.getenv("INDEX_NL_RESOLVER_MODEL", DEFAULT_MODEL),
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise NLResolverError(f"resolver LLM call failed: {exc}") from exc

    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise NLResolverError("resolver returned empty content")

    payload = _extract_json(text)
    try:
        parsed = _ResolverOutput(**payload)
    except ValidationError as exc:
        logger.warning("NL resolver output failed validation: %s; raw=%r", exc, text)
        raise NLResolverError(f"resolver output invalid: {exc}") from exc

    _enforce_whitelists(parsed.filters)
    keywords = [k.strip() for k in parsed.context_keywords if k and k.strip()][
        :MAX_KEYWORDS
    ]
    return parsed.filters, keywords


# -- helpers --------------------------------------------------------------


def _load_grounding(user_id: str) -> dict:
    rows = CodebaseContextDB().find_for_user(
        user_id, ["codebase_terminology", "query_refinement_hints"]
    )
    return {r.context_type: r.content for r in rows}


_SYSTEM_PROMPT = """You translate a single user query into a structured filter
plus an optional context keyword list. Reply with one JSON object only,
no prose, no code fences. The schema is:

{
  "filters": {
    "dependency": {"name": str, "version": str?, "op": "==|>=|<=|>|<|~="}?,
    "framework": str?,
    "language": str?,
    "platform": str?,
    "docker_image": {"name": str, "tag": str?}?,
    "github_action": {"owner": str, "name": str, "version_ref": str?}?,
    "has_file": str?,
    "workspace_manifest": str?
  },
  "context_keywords": [str, ...]
}

All filter keys are optional; omit any key you don't have evidence for.
Use canonical names from the vocabulary you are given. context_keywords
should be 0-5 short phrases drawn from the user's query for text search;
do not invent terms."""


def _build_prompt(nl_query: str, grounding: dict) -> str:
    parts = [f"Query: {nl_query}", "", "Vocabulary:"]
    parts.append(f"  frameworks: {sorted(vocab_mod.FRAMEWORKS)}")
    parts.append(f"  languages: {sorted(vocab_mod.LANGUAGES)}")
    parts.append(f"  platforms: {sorted(vocab_mod.PLATFORMS)}")
    parts.append(f"  has_file_whitelist: {sorted(PUBLIC_HAS_FILE_WHITELIST)}")
    parts.append(
        f"  workspace_manifest_whitelist: {sorted(PUBLIC_WORKSPACE_MANIFEST_WHITELIST)}"
    )
    if grounding.get("codebase_terminology"):
        parts.append("")
        parts.append("Codebase terminology:")
        parts.append(grounding["codebase_terminology"])
    if grounding.get("query_refinement_hints"):
        parts.append("")
        parts.append("Query refinement hints:")
        parts.append(grounding["query_refinement_hints"])
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Tolerate code fences if the model wraps them.
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NLResolverError(f"resolver returned non-JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NLResolverError("resolver JSON must be an object")
    return data


def _enforce_whitelists(filters: PublicSearchFilters) -> None:
    if filters.has_file and filters.has_file not in PUBLIC_HAS_FILE_WHITELIST:
        raise NLResolverError(f"has_file value not allowed: {filters.has_file}")
    if (
        filters.workspace_manifest
        and filters.workspace_manifest not in PUBLIC_WORKSPACE_MANIFEST_WHITELIST
    ):
        raise NLResolverError(
            f"workspace_manifest value not allowed: {filters.workspace_manifest}"
        )


__all__ = ["resolve_nl_query", "NLResolverError"]
