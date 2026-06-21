"""Devin CLI provider. See lib/cli/DEVIN.md for design rationale and verified facts."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from .base import CliProvider, CliRunConfig, CliResult
from .errors import CliError, CliRefusal

logger = logging.getLogger(__name__)


class DevinCli(CliProvider):
    name = "devin"

    def run(self, config: CliRunConfig) -> CliResult:
        session_id = config.resume_session_id or str(uuid4())
        is_resume = bool(config.resume_session_id)

        cmd = ["devin", "-p", "--permission-mode", "dangerous"]

        model = config.model or os.getenv("DEVIN_MODEL")
        if model:
            cmd += ["--model", model]

        # system_instructions are NOT session-sticky in Devin (verified: they are dropped
        # on -c resume). Pass --agent-config on EVERY call when system text is provided.
        agent_config_path: str | None = None
        if config.system:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            )
            json.dump({"system_instructions": [config.system]}, tmp)
            tmp.close()
            agent_config_path = tmp.name
            cmd += ["--agent-config", agent_config_path]

        if is_resume:
            cmd.append("-c")  # continues most-recent session in cwd (directory-keyed)

        cmd += ["--", config.prompt]

        env = os.environ.copy()
        env.update(config.env_overrides)

        logger.info(
            "DevinCli: cwd=%s session=%s resume=%s",
            config.cwd, session_id, is_resume,
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
            raise CliError(
                f"Devin CLI timed out after {config.timeout}s in {config.cwd}"
            ) from exc
        except OSError as exc:
            raise CliError(f"Devin CLI failed to start: {exc}") from exc
        finally:
            if agent_config_path:
                Path(agent_config_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            logger.error(
                "Devin CLI exited %d: stderr=%r stdout=%r",
                proc.returncode, stderr, stdout[:200],
            )
            # TODO: classify known refusal patterns into CliRefusal once a real
            # refusal response has been observed and its exit/stderr shape confirmed.
            raise CliError(f"Devin CLI exited {proc.returncode}: {stderr or stdout}")

        result_text = proc.stdout.strip()
        logger.info("DevinCli: done session=%s", session_id)

        return CliResult(
            result_text=result_text,
            session_id=session_id,   # presence token; resume keys on cwd via -c
            cost_usd=None,           # not available from Devin CLI
            usage={},
        )
