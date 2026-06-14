import json
import logging
import os
import subprocess

from .errors import APIError, InsufficientBalanceError
from .models import ClaudeRunConfig, ClaudeResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-6"


try:
    from langsmith import traceable as _traceable
    from langsmith.run_helpers import get_current_run_tree as _get_current_run_tree
except Exception:  # pragma: no cover - tracing is optional
    def _traceable(*args, **kwargs):
        def _decorator(fn):
            return fn

        if args and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

    def _get_current_run_tree():
        return None


def _record_claude_run_metadata(config: "ClaudeRunConfig", output: dict) -> None:
    """Attach cost / token / model metadata to the active LangSmith span."""
    run_tree = _get_current_run_tree()
    if run_tree is None:
        return
    usage = output.get("usage", {}) or {}
    metadata = {
        "cost_usd": output.get("total_cost_usd"),
        "model": config.model or os.getenv("CLAUDE_CLI_DEFAULT_MODEL"),
        "max_turns": config.max_turns,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
    }
    try:
        run_tree.add_metadata({k: v for k, v in metadata.items() if v is not None})
    except Exception:
        pass


class ClaudeCLIClient:
    """Single subprocess-based Claude CLI invocation primitive."""

    @_traceable(run_type="chain", name="claude-cli")
    def run(self, config: ClaudeRunConfig) -> ClaudeResult:
        cmd = [
            "claude",
            "-p", config.prompt,
            "--permission-mode", config.permission_mode,
            "--output-format", "json",
            "--max-turns", str(config.max_turns),
        ]

        model = config.model or os.getenv("CLAUDE_CLI_DEFAULT_MODEL")
        if model:
            cmd += ["--model", model]

        env = os.environ.copy()
        env.update(config.env_overrides)

        logger.info("Running Claude CLI in %s (max_turns=%d)", config.cwd, config.max_turns)

        proc = subprocess.run(
            cmd,
            cwd=config.cwd,
            capture_output=True,
            text=True,
            timeout=config.timeout,
            env=env,
        )

        if proc.returncode != 0:
            logger.error("Claude CLI exited %d: %s %s", proc.returncode, proc.stderr, proc.stdout)
            raise APIError(f"Claude CLI exited {proc.returncode}: {proc.stderr}")

        try:
            output = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise APIError(f"Could not parse Claude CLI JSON output: {exc} | {proc.stdout[:500]}") from exc

        if output.get("is_error"):
            result_text = output.get("result", "")
            if "Insufficient Balance" in result_text:
                raise InsufficientBalanceError(result_text)
            raise APIError(f"Claude CLI error: {result_text}")

        if "total_cost_usd" not in output:
            raise APIError(f"total_cost_usd missing from Claude CLI output: {proc.stdout[:500]}")

        usage = output.get("usage", {})
        logger.info(
            "Claude CLI cost=%.6f input=%s output=%s cache_read=%s",
            output["total_cost_usd"],
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            usage.get("cache_read_input_tokens", 0),
        )

        _record_claude_run_metadata(config, output)
        return ClaudeResult(cost_usd=output["total_cost_usd"], usage=usage)
