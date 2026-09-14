"""MCP server factory — returns a configured FastMCP app."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import ToolAnnotations

from lib.tracing import is_tracing_enabled

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class _ToolCallTracer(Middleware):
    """Open a LangSmith root span per MCP tool call."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
        arguments = context.message.arguments
        logging.getLogger("mcp_server").debug("tool_call → %s args=%s", tool_name, arguments)

        if not is_tracing_enabled():
            try:
                return await call_next(context)
            finally:
                logging.getLogger("mcp_server").debug("tool_call ← %s", tool_name)

        try:
            from langsmith import trace
        except Exception:
            return await call_next(context)

        started = time.perf_counter()
        with trace(
            name=f"mcp.{tool_name}",
            run_type="chain",
            inputs={"arguments": arguments},
            metadata={"service": "mcp-server", "tool": tool_name},
            tags=["mcp", "tool"],
        ) as run:
            try:
                result = await call_next(context)
            except Exception as exc:
                run.end(error=str(exc))
                raise
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            try:
                run.add_metadata({"elapsed_ms": elapsed_ms})
                run.end(outputs={"result": result})
            except Exception:
                pass
            logging.getLogger("mcp_server").debug("tool_call ← %s (%.0fms)", tool_name, elapsed_ms)
            return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_RO = ToolAnnotations(readOnlyHint=True)
_IDEM = ToolAnnotations(destructiveHint=False, idempotentHint=True)
_DEST = ToolAnnotations(destructiveHint=True)


def create_app(
    *,
    name: str = "service-catalog",
    instructions: str,
    auth=None,
    tools: list,
    tool_annotations: Optional[dict] = None,
    workspace,
    scheduler,
):
    @asynccontextmanager
    async def _lifespan(app):
        from lib.async_utils import set_main_event_loop

        set_main_event_loop(asyncio.get_running_loop())
        yield {"workspace": workspace, "scheduler": scheduler}
        try:
            await scheduler.shutdown()
        except Exception:
            pass

    app = FastMCP(
        name,
        instructions=instructions,
        auth=auth,
        lifespan=_lifespan,
    )
    app.add_middleware(_ToolCallTracer())

    annotations = tool_annotations or {}

    for tool_fn in tools:
        annot = annotations.get(tool_fn.__name__)
        if annot:
            app.tool(tool_fn, annotations=annot)
        else:
            app.tool(tool_fn)

    return app
