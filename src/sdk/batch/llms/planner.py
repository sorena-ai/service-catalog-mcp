"""Planner sub-LLM — Sonnet structured output → Task + per-repo descriptions."""

from __future__ import annotations

import logging

import anthropic

from sdk.batch.models import BatchSession

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are a code-change planner. Given a user's batch change request and a list of
target repositories, you produce:
  1. A single refined task description (rich markdown, max ~300 words) describing
     what needs to change and the key invariants / risks to watch for.
  2. A per-repo description for each repository (concise, 2–5 sentences) explaining
     what specifically needs to change in that repo, informed by the task context.

Be specific and actionable. Think about cross-repo consistency where relevant.
If the hint history is non-empty, incorporate the most recent guidance.
"""

_TOOL: dict = {
    "name": "set_plan",
    "description": "Record the planner output",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Refined overall task (markdown)",
            },
            "per_repo_descriptions": {
                "type": "object",
                "description": "Keys are 'owner/repo'; values are concise per-repo plans",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["task_description", "per_repo_descriptions"],
    },
}


class PlannerOutput:
    def __init__(self, task_description: str, per_repo_descriptions: dict[str, str]) -> None:
        self.task_description = task_description
        self.per_repo_descriptions = per_repo_descriptions


async def run_planner(session: BatchSession) -> PlannerOutput:
    """Call Sonnet to produce a refined task + per-repo descriptions."""
    repos = list(session.sub_tasks.keys())
    history_text = ""
    if session.history:
        history_text = "\n\nRefinement hints (oldest first):\n" + "\n".join(
            f"- {h.text}" for h in session.history
        )

    user_msg = (
        f"Query: {session.query}\n\n"
        f"Repositories:\n" + "\n".join(f"- {r}" for r in repos) + history_text
    )

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "set_plan"},
        messages=[{"role": "user", "content": user_msg}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError("Planner returned no structured output")
    inp = tool_use.input
    return PlannerOutput(
        task_description=inp["task_description"],
        per_repo_descriptions=inp["per_repo_descriptions"],
    )
