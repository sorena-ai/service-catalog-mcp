"""CLI provider layer.

Selects the active provider from the CLI_PROVIDER env var (default: "claude").

Usage:
    from lib.cli import get_cli
    from lib.cli.base import CliRunConfig

    cli = get_cli()
    result = cli.run(CliRunConfig(cwd=..., prompt=...))
"""

from __future__ import annotations

import os

from .base import CliProvider, CliResult, CliRunConfig
from .errors import CliError, CliInsufficientBalance, CliRefusal

_PROVIDERS: dict[str, type[CliProvider]] = {}


def _register():
    from .claude import ClaudeCli
    from .devin import DevinCli
    _PROVIDERS["claude"] = ClaudeCli
    _PROVIDERS["devin"] = DevinCli


def get_cli(provider: str | None = None) -> CliProvider:
    if not _PROVIDERS:
        _register()
    name = provider or os.getenv("CLI_PROVIDER", "claude")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown CLI provider {name!r}. Choose from: {list(_PROVIDERS)}")
    return cls()


__all__ = [
    "get_cli",
    "CliProvider",
    "CliRunConfig",
    "CliResult",
    "CliError",
    "CliRefusal",
    "CliInsufficientBalance",
]
