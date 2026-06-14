"""MCP-layer error translation.

Converts SDK domain exceptions into FastMCP ToolErrors at the tool boundary.
Apply @translate_sdk_errors to every tool function — one decorator replaces
the ~25 repeated try/except blocks that existed in bridge.py.
"""

from __future__ import annotations

import functools
from typing import Callable

from fastmcp.exceptions import ToolError

from sdk.errors import (
    ConflictError,
    GitHubAppNotInstalledError,
    InvalidRequestError,
    NotFoundError,
    SdkError,
)


def to_tool_error(exc: SdkError) -> ToolError:
    if isinstance(exc, GitHubAppNotInstalledError):
        suffix = f" Install it at: {exc.install_url}" if exc.install_url else ""
        return ToolError(f"{exc}{suffix}")
    if isinstance(exc, NotFoundError):
        return ToolError(f"Not found: {exc}")
    if isinstance(exc, InvalidRequestError):
        return ToolError(f"Invalid request: {exc}")
    if isinstance(exc, ConflictError):
        return ToolError(str(exc))
    return ToolError(str(exc))


def translate_sdk_errors(fn: Callable) -> Callable:
    """Decorator: catch SdkError from the wrapped tool and raise ToolError."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except SdkError as exc:
            raise to_tool_error(exc)
    return wrapper
