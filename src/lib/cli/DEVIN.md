# Devin CLI Provider — Implementation Plan

`DevinCli` in `devin.py` is currently a stub that raises `NotImplementedError`.
This document captures everything needed to make it real.

## What we know (from `devin --help` and docs)

```
devin -p "prompt"               # non-interactive, stdout = response text
devin -p -c                     # continue most recent session in cwd (non-interactive)
devin --permission-mode dangerous
devin --model <model>           # env: DEVIN_MODEL
devin --agent-config <file>     # declarative JSON/YAML: system instructions, tool visibility
devin list --format json        # sessions scoped to cwd, each has "id" + "working_directory"
```

Sessions are **directory-keyed**: `devin list` only shows sessions whose
`working_directory` matches the current cwd.

## Gap table vs Claude CLI

| Feature | Claude | Devin | Design |
|---|---|---|---|
| Run / output format | `--output-format json` | plain text on stdout | capture stdout as `result_text` |
| Session ID at creation | `--session-id <uuid>` (we supply it) | not supported | generate uuid4 as presence token; store and pass back as `session_id` (never sent to binary) |
| Resume | `-r <uuid>` | `-p -c` in same cwd (directory-keyed) | presence token tells us a session exists; `-c` picks it up via cwd |
| System prompt | `--system-prompt` | `--agent-config <file>` | write a temp JSON file with `{"system": "..."}`, pass via `--agent-config` |
| Cost / usage | in JSON output | not available | return `cost_usd=None`, `usage={}` |
| max_turns | `--max-turns N` | not available | silently ignore |
| Permission mode | `acceptEdits` | `--permission-mode dangerous` | hardcode `dangerous` |
| Errors | JSON `is_error` field | non-zero exit + stderr | map exit code to `CliError`; map known refusal strings to `CliRefusal` |

## Implementation sketch

```python
import json
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from .base import CliProvider, CliRunConfig, CliResult
from .errors import CliError, CliRefusal

class DevinCli(CliProvider):
    name = "devin"

    def run(self, config: CliRunConfig) -> CliResult:
        session_id = config.resume_session_id or str(uuid4())
        is_resume = bool(config.resume_session_id)

        cmd = ["devin", "-p", "--permission-mode", "dangerous"]

        model = config.model or os.getenv("DEVIN_MODEL")
        if model:
            cmd += ["--model", model]

        # system prompt only on first run, via agent-config file
        agent_config_path = None
        if config.system and not is_resume:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            )
            json.dump({"system": config.system}, tmp)
            tmp.close()
            agent_config_path = tmp.name
            cmd += ["--agent-config", agent_config_path]

        if is_resume:
            cmd.append("-c")

        # prompt goes after --
        cmd += ["--", config.prompt]

        env = os.environ.copy()
        env.update(config.env_overrides)

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
            raise CliError(f"Devin CLI timed out after {config.timeout}s in {config.cwd}") from exc
        except OSError as exc:
            raise CliError(f"Devin CLI failed to start: {exc}") from exc
        finally:
            if agent_config_path:
                Path(agent_config_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            # TODO: map known refusal strings to CliRefusal once patterns confirmed
            raise CliError(f"Devin CLI exited {proc.returncode}: {stderr}")

        result_text = proc.stdout.strip()

        return CliResult(
            result_text=result_text,
            session_id=session_id,
            cost_usd=None,    # not available from Devin CLI
            usage={},
        )
```

## Things to verify before merging

1. **`--agent-config` system instructions format** — confirm the JSON key is `"system"`.
   Run: `echo '{"system": "say hi"}' > /tmp/test.json && devin -p --agent-config /tmp/test.json -- "what are your instructions?"`

2. **`-p -c` non-interactive** — confirm `-c` works in print mode (no REPL).
   Run in a dir with an existing session: `devin -p -c -- "follow-up message"`

3. **Refusal detection** — run a prompt Devin declines to confirm what exit code / stderr pattern to catch as `CliRefusal`.

4. **`devin list --format json` schema** — already confirmed: `{"id": "...", "working_directory": "...", ...}`. No action needed.

## What callers need to know

Nothing. The `CliRunConfig` / `CliResult` contract is identical to Claude.
`cost_usd=None` is already handled by the LangSmith recorder (it skips `None` fields)
and by the indexer's `runs_db.update(... "cost_usd": result.cost_usd ...)` — MongoDB
accepts `None` as a no-op on that field.
