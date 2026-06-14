"""Utilities for running async coroutines from sync contexts."""
import asyncio
from typing import Callable, Coroutine, Any

# Global variable to hold the main event loop
main_event_loop = None

def set_main_event_loop(loop: asyncio.AbstractEventLoop):
    """Set the main event loop for the application."""
    global main_event_loop
    main_event_loop = loop

def run_async_from_sync(coro: Callable[..., Coroutine], *args: Any, **kwargs: Any) -> Any:
    """
    Run an async function from a synchronous context.

    Args:
        coro: The async function (coroutine) to run.
        *args: Positional arguments for the coroutine.
        **kwargs: Keyword arguments for the coroutine.

    Returns:
        The result of the coroutine.
    """
    if main_event_loop is None:
        raise RuntimeError("Main event loop has not been set. Call set_main_event_loop on startup.")

    future = asyncio.run_coroutine_threadsafe(coro(*args, **kwargs), main_event_loop)
    return future.result()
