"""LangSmith-instrumented client factories.

``traced_anthropic_client`` returns an Anthropic client wrapped with
``langsmith.wrappers.wrap_anthropic`` when tracing is enabled, or a plain
``anthropic.Anthropic`` otherwise. Call sites stay identical either way.
"""

from __future__ import annotations

import logging
from typing import Any

from .config import is_tracing_enabled

logger = logging.getLogger(__name__)


def traced_anthropic_client(api_key: str | None = None) -> Any:
    """Return a (possibly wrapped) Anthropic client.

    Imports the SDK lazily so the helper still imports in environments
    where ``anthropic`` is not installed (e.g. mcp-server).
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    if not is_tracing_enabled():
        return client

    try:
        from langsmith.wrappers import wrap_anthropic

        return wrap_anthropic(client)
    except Exception as exc:
        logger.warning("Could not wrap Anthropic client for LangSmith: %s", exc)
        return client
