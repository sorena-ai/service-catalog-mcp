# Devin CLI Provider — Implementation Plan

`DevinCli` in `devin.py` is currently a stub that raises `NotImplementedError`.
This document is the spec for making it real. Everything below was **verified by
running `devin` locally** (authed as a real user), not inferred from docs.

## Verified facts (live, 2026-06)

```
devin -p -- "prompt"                  # non-interactive; stdout = plain response text only
devin -p -c -- "prompt"               # continue most recent session in cwd (non-interactive)
devin -p --agent-config <file> -- ".." # apply declarative config (system instructions etc.)
devin --permission-mode dangerous     # modes: auto | smart | dangerous (NO "acceptEdits")
devin --model <model>                 # env: DEVIN_MODEL
devin list --format json              # sessions in cwd: [{id, short_id, working_directory, ...}]
```

1. **stdout format** — plain text, just the agent's response. No JSON envelope,
   **no session id or cost printed**. Capture stdout verbatim as `result_text`.

2. **agent-config schema is strict-parsed** (unknown keys rejected). Valid keys:
   `system_instructions` / `system-instructions`, `allowed_tools`, `permissions`,
   `mcp_servers`, `extensions`.
   - `system_instructions` **must be an array of strings**, not a string.
     `{"system_instructions": ["..."]}` works; a bare string errors.
   - Parse errors exit **before** a session is created (exit 1, nothing billed).

3. **Sessions are directory-keyed.** `devin list --format json` only shows
   sessions whose `working_directory` matches the cwd. Each has `id` == `short_id`
   (a slug like `cooked-exhaust`). ⚠️ On macOS `working_directory` is the *resolved*
   path (`/tmp` → `/private/tmp`), so do **not** match cwd by string — rely on
   `-c` (which keys on cwd internally).

4. **`-p -c` works non-interactively** and continues the most recent session in
   the cwd. Safe even when no session exists yet — it just starts a fresh one.

5. **🔴 `system_instructions` do NOT persist across `-c` resume.** A session
   created with `--agent-config` and then resumed via `-p -c` *without* the config
   loses those instructions (verified: the rule was dropped on resume). The
   conversation history carries over, but the config does not.

## The design consequence of fact #5

Claude's system prompt is sticky for the life of the session, so we set it only on
the first run. **Devin's is not** — so for Devin we must pass `--agent-config` on
**every** call where guardrails matter (e.g. batch's "don't commit/push").

Resolution — keep one caller contract, let each provider decide when to apply it:

- **Caller always passes `config.system`** (first run *and* resume).
- **ClaudeCli**: applies `--system-prompt` only on first run (when not resuming);
  ignores `system` on resume. This is already the current behavior — no change.
- **DevinCli**: writes an agent-config with `system_instructions=[config.system]`
  and passes `--agent-config` on **every** call.

Only change required at a call site: `sdk/batch/diff.py::chat_repo` must pass
`system=` on its resume calls (today it passes none). ClaudeCli ignores it, so this
is safe for the Claude path. The indexer passes no system at all (its prompts are
self-contained), so it is unaffected.

## Gap table vs Claude CLI

| Feature | Claude | Devin | Design |
|---|---|---|---|
| Run / output | `--output-format json` | plain-text stdout | capture stdout as `result_text` |
| Session id at creation | `--session-id <uuid>` | not supported | generate uuid4 as a presence token; return it as `session_id`, never sent to the binary |
| Resume | `-r <uuid>` | `-p -c` in same cwd (dir-keyed) | the token signals "a session exists"; `-c` picks it up via cwd |
| System prompt | `--system-prompt`, session-sticky | `--agent-config` `system_instructions: [..]`, **not** sticky | pass agent-config on **every** call (see above) |
| Cost / usage | in JSON | not available | `cost_usd=None`, `usage={}` |
| max_turns | `--max-turns N` | not available | silently ignore |
| Permission mode | `acceptEdits` | `dangerous` (auto/smart/dangerous) | hardcode `dangerous` for edit parity |
| Model | `--model` (env `CLAUDE_CLI_DEFAULT_MODEL`) | `--model` (env `DEVIN_MODEL`) | use `config.model` or `DEVIN_MODEL` |
| Errors | JSON `is_error` | non-zero exit + stderr | exit!=0 → `CliError`; map known refusal strings → `CliRefusal` (TBD) |

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

        # Devin does NOT persist system_instructions across resume, so pass the
        # agent-config on EVERY call when system text is provided (note: array).
        agent_config_path = None
        if config.system:
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump({"system_instructions": [config.system]}, tmp)
            tmp.close()
            agent_config_path = tmp.name
            cmd += ["--agent-config", agent_config_path]

        if is_resume:
            cmd.append("-c")            # continue latest session in cwd

        cmd += ["--", config.prompt]    # prompt after the -- separator

        env = os.environ.copy()
        env.update(config.env_overrides)

        try:
            proc = subprocess.run(
                cmd, cwd=config.cwd, capture_output=True, text=True,
                timeout=config.timeout, env=env,
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
            # TODO: classify refusals -> CliRefusal once a real pattern is seen
            raise CliError(f"Devin CLI exited {proc.returncode}: {stderr}")

        return CliResult(
            result_text=proc.stdout.strip(),
            session_id=session_id,   # presence token; resume keys on cwd via -c
            cost_usd=None,           # not available from Devin CLI
            usage={},
        )
```

## Still open (settle during implementation)

1. **Refusal detection** — we haven't seen a real Devin refusal yet, so the
   `exit!=0 → CliRefusal` mapping is unimplemented. Trigger one declined task and
   inspect exit code + stderr, then add the classification. Until then everything
   non-zero is `CliError` (internal), which is the safe default.

2. **`chat_repo` system passthrough** — make `sdk/batch/diff.py::chat_repo` pass
   `system=` on resume (see "design consequence" above). Small, isolated edit.

3. **Timeouts** — batch uses 1800s; Devin sessions are cloud-backed and may run
   longer than local Claude. Watch for `TimeoutExpired` and tune if needed.

## What callers need to know

Almost nothing. The `CliRunConfig` / `CliResult` contract is identical to Claude;
`cost_usd=None` is already handled (LangSmith recorder skips `None`; the indexer
writes `None` to Mongo as a no-op). The only call-site change is item #2 above.
