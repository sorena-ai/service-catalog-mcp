"""Provider-neutral CLI exceptions.

These replace the per-provider exceptions (claude_cli's ClaudeCLIError /
InsufficientBalanceError / APIError and batch's ExternalRefusal) at the
call sites that go through the `cli` layer. Each provider implementation
raises these neutral types so callers never branch on the active provider.
"""


class CliError(Exception):
    """Process-level or unexpected CLI failure — classify as internal."""


class CliRefusal(CliError):
    """The agent refused the task (is_error in CLI output) — do not retry."""


class CliInsufficientBalance(CliError):
    """The CLI reported insufficient balance / quota."""
