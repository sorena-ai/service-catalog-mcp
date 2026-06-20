"""Claude CLI provider — absorbs ClaudeCLIClient and ResumableClaudeRunner."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from uuid import uuid4

from .base import CliProvider, CliRunConfig, CliResult
from .errors import CliError, CliInsufficientBalance, CliRefusal

logger = logging.getLogger(__name__)

try:
    from langsmith import traceable as _traceable
    from langsmith.run_helpers import get_current_run_tree as _get_current_run_tree
except Exception:
    def _traceable(*args, **kwargs):
        def _decorator(fn):
            return fn
        if args and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

    def _get_current_run_tree():
        return None


def _record_metadata(config: CliRunConfig, output: dict) -> None:
    run_tree = _get_current_run_tree()
    if run_tree is None:
        return
    usage = output.get("usage") or {}
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


class ClaudeCli(CliProvider):
    name = "claude"

    @_traceable(run_type="chain", name="claude-cli")
    def run(self, config: CliRunConfig) -> CliResult:
        session_id = config.resume_session_id or str(uuid4())

        cmd = [
            "claude",
            "-p", config.prompt,
            "--permission-mode", "acceptEdits",
            "--output-format", "json",
            "--max-turns", str(config.max_turns),
            "--session-id", session_id,
        ]

        model = config.model or os.getenv("CLAUDE_CLI_DEFAULT_MODEL")
        if model:
            cmd += ["--model", model]

        # system prompt only on first run (no resume)
        if config.system and not config.resume_session_id:
            cmd += ["--system-prompt", config.system]

        env = os.environ.copy()
        env.update(config.env_overrides)

        logger.info(
            "ClaudeCli: cwd=%s session=%s resume=%s max_turns=%d",
            config.cwd, session_id, bool(config.resume_session_id), config.max_turns,
        )

        try:
            proc = subprocess.run(
                cmd,
                cwd=config.cwd,
                capture_output=True,
                text=True,
                timeout=config.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise CliError(f"Claude CLI timed out after {config.timeout}s in {config.cwd}") from exc
        except OSError as exc:
            raise CliError(f"Claude CLI failed to start: {exc}") from exc

        if proc.returncode != 0:
            logger.error("Claude CLI exited %d: %s %s", proc.returncode, proc.stderr, proc.stdout)
            raise CliError(f"Claude CLI exited {proc.returncode}: {proc.stderr}")

        try:
            output = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise CliError(f"Could not parse Claude CLI JSON: {exc} | {proc.stdout[:500]}") from exc

        if output.get("is_error"):
            result_text = output.get("result", "")
            if "Insufficient Balance" in result_text:
                raise CliInsufficientBalance(result_text)
            raise CliRefusal(result_text)

        result_text = output.get("result", "")
        cost_usd = output.get("total_cost_usd")
        usage = output.get("usage") or {}

        _record_metadata(config, output)
        logger.info(
            "ClaudeCli: done session=%s cost=%.6f input=%s output=%s",
            session_id, cost_usd or 0.0, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
        )

        return CliResult(
            result_text=result_text,
            session_id=session_id,
            cost_usd=cost_usd,
            usage=usage,
        )
