"""PR drafter sub-LLM — Haiku structured output → {title, body}."""

from __future__ import annotations

import logging

import anthropic

from sdk.batch.models import FileStat

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM = """\
You are writing a GitHub pull request description for one repository in a batch code change.

Write a lean PR:
- Title: short (≤ 72 chars), imperative mood, no preamble.
- Body: 2–5 sentences specific to this repo's changes. End with one line starting
  "References:" if the overall task mentions cross-repo concerns (e.g. shared API
  contracts, coordinated releases). No markdown headers. No bullet lists. Plain prose.
"""

_TOOL: dict = {
    "name": "set_pr",
    "description": "Record the PR title and body",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR title (≤ 72 chars, imperative)"},
            "body": {"type": "string", "description": "PR body (plain prose, 2–5 sentences)"},
        },
        "required": ["title", "body"],
    },
}


class DraftOutput:
    def __init__(self, title: str, body: str) -> None:
        self.title = title
        self.body = body


async def draft_pr(
    task_description: str,
    sub_task_description: str,
    one_line_summary: str,
    file_stats: list[FileStat],
) -> DraftOutput:
    """Call Haiku to draft a PR title and body."""
    file_list = "\n".join(
        f"  {f.path} (+{f.additions}/-{f.deletions})" for f in file_stats
    ) or "  (none)"

    user_msg = (
        f"Overall task:\n{task_description}\n\n"
        f"This repo's sub-task:\n{sub_task_description}\n\n"
        f"What was done (summary):\n{one_line_summary}\n\n"
        f"Files changed:\n{file_list}"
    )

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "set_pr"},
        messages=[{"role": "user", "content": user_msg}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError("PR drafter returned no structured output")
    inp = tool_use.input
    return DraftOutput(title=inp["title"], body=inp["body"])
