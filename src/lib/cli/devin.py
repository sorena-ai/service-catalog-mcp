"""Devin CLI provider — stub. See lib/cli/DEVIN.md for the implementation plan."""

from __future__ import annotations

from .base import CliProvider, CliRunConfig, CliResult


class DevinCli(CliProvider):
    name = "devin"

    def run(self, config: CliRunConfig) -> CliResult:
        raise NotImplementedError(
            "DevinCli is not yet implemented. "
            "See src/lib/cli/DEVIN.md for the full implementation plan."
        )
