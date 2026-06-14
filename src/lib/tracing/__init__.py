"""Shared LangSmith tracing utilities.

All three Python services (mcp-server, core, agent) call ``setup_tracing``
once at startup and use the helpers here to:

  - Wrap Anthropic clients so every ``messages.create`` becomes a span.
  - Attach ``@traceable`` to chain functions (orchestrators, LLM helpers).
  - Propagate trace context across HTTP boundaries via dotted-order headers
    so an MCP tool call → core route → agent route lands in one trace.

When ``LANGSMITH_TRACING`` is unset / "false" or ``LANGSMITH_API_KEY`` is
missing, every helper degrades to a soft no-op and the call sites still
work.
"""

from .config import (
    setup_tracing,
    is_tracing_enabled,
    service_name,
)
from .clients import traced_anthropic_client
from .propagation import (
    TRACE_HEADER,
    PARENT_HEADER,
    inject_trace_headers,
    extract_trace_headers,
    incoming_trace_context,
    capture_current_run_headers,
    use_remote_run_headers,
)

__all__ = [
    "setup_tracing",
    "is_tracing_enabled",
    "service_name",
    "traced_anthropic_client",
    "TRACE_HEADER",
    "PARENT_HEADER",
    "inject_trace_headers",
    "extract_trace_headers",
    "incoming_trace_context",
    "capture_current_run_headers",
    "use_remote_run_headers",
]
