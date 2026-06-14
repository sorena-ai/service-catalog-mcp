"""Domain exceptions for the SDK.

These are protocol-neutral — no HTTP status codes, no FastAPI/MCP types.
Each edge (MCP, FastAPI) maps these to its own error type.
"""

from __future__ import annotations


class SdkError(Exception):
    """Base for all domain errors raised by the SDK."""


class NotFoundError(SdkError):
    """A requested resource does not exist."""


class ConflictError(SdkError):
    """The operation conflicts with current state or a precondition is unmet."""


class InvalidRequestError(SdkError):
    """Arguments are structurally invalid for the operation."""


class GitHubAppNotInstalledError(SdkError):
    """GitHub App is not installed for this user."""

    def __init__(self, message: str = "GitHub App is not installed.", install_url: str = ""):
        super().__init__(message)
        self.install_url = install_url


__all__ = [
    "SdkError",
    "NotFoundError",
    "ConflictError",
    "InvalidRequestError",
    "GitHubAppNotInstalledError",
]
