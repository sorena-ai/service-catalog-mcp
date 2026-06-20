from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CliRunConfig:
    cwd: Path
    prompt: str
    system: Optional[str] = None
    resume_session_id: Optional[str] = None
    model: Optional[str] = None
    max_turns: int = 100
    timeout: int = 1800
    env_overrides: dict = field(default_factory=dict)


@dataclass
class CliResult:
    result_text: str
    session_id: Optional[str]
    cost_usd: Optional[float]
    usage: dict


class CliProvider(ABC):
    name: str

    @abstractmethod
    def run(self, config: CliRunConfig) -> CliResult: ...
