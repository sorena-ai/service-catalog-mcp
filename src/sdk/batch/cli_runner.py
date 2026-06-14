"""Per-repo Claude CLI runner with resume support."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ClaudeCLIError(RuntimeError):
    """Process-level or network failure — classify as internal."""


class ExternalRefusal(ClaudeCLIError):
    """Claude refused the task (is_error=True in JSON output) — no retry."""


class ResumableClaudeRunner:
    """Runs claude CLI subprocess; captures session_id; supports --resume for iterations."""

    def run(
        self,
        cwd: Path,
        prompt: str,
        system: Optional[str],
        resume_session_id: Optional[str],
        max_turns: int = 50,
    ) -> tuple[str, float]:
        """Return (session_id, total_cost_usd)."""
        cmd = [
            "claude",
            "-p", prompt,
            "--permission-mode", "acceptEdits",
            "--output-format", "json",
            "--max-turns", str(max_turns),
        ]
        if resume_session_id:
            cmd += ["--resume", resume_session_id]
        elif system:
            cmd += ["--system-prompt", system]

        logger.info("Running ResumableClaudeRunner in %s (resume=%s)", cwd, resume_session_id)
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=1800,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCLIError(f"Claude CLI timed out after 1800s in {cwd}") from exc
        except OSError as exc:
            raise ClaudeCLIError(f"Claude CLI failed to start: {exc}") from exc

        if proc.returncode != 0:
            logger.error(
                "Claude CLI exited %d stderr=%s stdout=%s",
                proc.returncode, proc.stderr[:500], proc.stdout[:200],
            )
            raise ClaudeCLIError(
                f"Claude CLI exited {proc.returncode}: {proc.stderr[:500]}"
            )

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCLIError(
                f"Could not parse Claude CLI JSON: {exc} | {proc.stdout[:300]}"
            ) from exc

        if data.get("is_error"):
            raise ExternalRefusal(data.get("result", "Claude refused the task"))

        session_id: Optional[str] = data.get("session_id")
        if not session_id:
            raise ClaudeCLIError(f"session_id missing from CLI output: {proc.stdout[:300]}")

        result_text: str = data.get("result", "")
        cost: float = data.get("total_cost_usd", 0.0)
        logger.info("CLI run done session=%s cost=%.4f", session_id, cost)
        return session_id, result_text, cost
