"""Cross-service trace propagation helpers.

LangSmith propagates trace context with the ``langsmith-trace`` header
(and optional ``baggage``). On the server side, ``TracingMiddleware``
from ``langsmith.middleware`` reads the headers off the FastAPI request
and starts the request-scoped tracing context.

On the client side (mcp-server → core, core → agent) we read the current
``RunTree`` and merge ``to_headers()`` into outgoing httpx requests so
the downstream span is parented under the originating MCP tool call.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator, Mapping, MutableMapping

from .config import is_tracing_enabled

logger = logging.getLogger(__name__)

TRACE_HEADER = "langsmith-trace"
PARENT_HEADER = "langsmith-parent"


def inject_trace_headers(
    headers: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Return ``headers`` plus the current run's LangSmith propagation headers.

    Safe to call when tracing is disabled or no run is active — returns
    the original headers unchanged. Does not mutate ``headers``.
    """
    out: dict[str, str] = dict(headers or {})
    if not is_tracing_enabled():
        return out

    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree is not None:
            out.update(run_tree.to_headers())
    except Exception as exc:
        logger.debug("inject_trace_headers no-op: %s", exc)
    return out


def extract_trace_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Pull only the LangSmith propagation headers from a request.

    Useful when manually starting a child trace inside a worker that did
    not enter through ``TracingMiddleware`` (e.g. a thread-pool job).
    """
    keys = {TRACE_HEADER, "baggage", PARENT_HEADER}
    return {k: v for k, v in headers.items() if k.lower() in keys}


@contextlib.contextmanager
def incoming_trace_context(headers: Mapping[str, str]) -> Iterator[None]:
    """Enter the LangSmith tracing context carried by ``headers``.

    Use this inside background tasks / thread workers that need to
    re-enter a parent trace propagated from another service. FastAPI
    routes get this for free via ``TracingMiddleware``.
    """
    if not is_tracing_enabled():
        yield
        return
    try:
        import langsmith as ls

        with ls.tracing_context(parent=dict(headers)):
            yield
    except Exception as exc:
        logger.debug("incoming_trace_context no-op: %s", exc)
        yield


def capture_current_run_headers() -> dict[str, str]:
    """Snapshot the current run's headers for hand-off to a worker thread.

    Returns ``{}`` when tracing is disabled or no run is active.
    """
    if not is_tracing_enabled():
        return {}
    try:
        from langsmith.run_helpers import get_current_run_tree

        run_tree = get_current_run_tree()
        if run_tree is None:
            return {}
        return dict(run_tree.to_headers())
    except Exception as exc:
        logger.debug("capture_current_run_headers no-op: %s", exc)
        return {}


@contextlib.contextmanager
def use_remote_run_headers(headers: Mapping[str, str] | None) -> Iterator[None]:
    """Re-enter a parent trace from snapshotted headers.

    Pair with :func:`capture_current_run_headers` to bridge a thread
    boundary, e.g.::

        parent = capture_current_run_headers()
        executor.submit(_worker, parent, ...)

        # in worker:
        with use_remote_run_headers(parent):
            do_work()
    """
    if not headers:
        yield
        return
    with incoming_trace_context(headers):
        yield
