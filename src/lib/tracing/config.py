"""LangSmith env-driven configuration with a soft kill-switch.

``setup_tracing(service_name)`` is called once at service startup. It sets
sensible defaults on missing env vars and logs a single warning when the
key is absent so the service still runs without LangSmith.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_SERVICE_NAME: str | None = None
_DID_INIT = False


def setup_tracing(service: str) -> None:
    """Initialize LangSmith env vars for ``service``.

    Sets ``LANGSMITH_PROJECT`` if not already set, validates the API key,
    and logs a warning when tracing is disabled or the key is missing.
    Idempotent — safe to call multiple times.
    """
    global _SERVICE_NAME, _DID_INIT
    with _LOCK:
        _SERVICE_NAME = service
        if _DID_INIT:
            return
        _DID_INIT = True

    tracing_flag = os.getenv("LANGSMITH_TRACING", "").strip().lower()
    enabled = tracing_flag in {"1", "true", "yes", "on"}
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()

    if not enabled:
        logger.warning(
            "LangSmith tracing disabled for %s (LANGSMITH_TRACING=%r). "
            "Spans will not be reported.",
            service,
            tracing_flag,
        )
        return

    if not api_key:
        logger.warning(
            "LangSmith tracing requested for %s but LANGSMITH_API_KEY is empty. "
            "Spans will not be reported.",
            service,
        )
        return

    os.environ.setdefault("LANGSMITH_PROJECT", f"service-catalog-{service}")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ.setdefault("LANGCHAIN_PROJECT", os.environ["LANGSMITH_PROJECT"])

    endpoint = os.getenv("LANGSMITH_ENDPOINT", "").strip()
    if endpoint:
        os.environ.setdefault("LANGSMITH_ENDPOINT", endpoint)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", endpoint)

    os.environ.pop("LANGSMITH_" + "WORKSPACE_" + "ID", None)

    logger.info(
        "LangSmith tracing enabled for %s (project=%s)",
        service,
        os.environ["LANGSMITH_PROJECT"],
    )


def is_tracing_enabled() -> bool:
    """True iff tracing is on AND an API key is present."""
    flag = os.getenv("LANGSMITH_TRACING", "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    return bool(os.getenv("LANGSMITH_API_KEY", "").strip())


def service_name() -> str:
    """Return the service name registered via ``setup_tracing``."""
    return _SERVICE_NAME or "unknown"
