from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClaudeRunConfig:
    cwd: str
    prompt: str
    # If set, passed as --model flag. None = let env ANTHROPIC_MODEL / CLAUDE_CLI_DEFAULT_MODEL govern.
    model: Optional[str] = None
    max_turns: int = 100
    permission_mode: str = "acceptEdits"
    # Extra env vars merged on top of os.environ (e.g. DeepSeek routing overrides).
    env_overrides: dict = field(default_factory=dict)
    timeout: int = 300


@dataclass
class ClaudeResult:
    cost_usd: float
    usage: dict
