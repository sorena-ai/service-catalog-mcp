# mcp-server

FastMCP protocol adapter for Claude Desktop. Runs on port 8200. Pure tool layer — imports business logic directly from `sdk/` packages. All business logic is a direct Python call (no HTTP to a separate service).

## Responsibility

- Expose MCP tools to Claude Desktop
- Provide server-level `instructions` that walk Claude through the conversational batch flow
- Validate Auth0 JWT (cloud) or GITHUB_TOKEN (local) on every request and resolve the internal user_id
- Pass `workspace` and `scheduler` to every tool via `ctx.lifespan_context`
- Format responses for LLM consumption (typed Pydantic return models)

## Directory layout

```
src/mcp_server/
├── app.py         FastMCP factory — create_app(), _ToolCallTracer middleware, ToolAnnotations constants
│                  Lifespan yields {"workspace": Workspace, "scheduler": IndexingScheduler}
├── main.py        Entrypoint — LOCAL/cloud mode split, _BASE_TOOLS/_ACCOUNT_TOOLS lists,
│                  _LOCAL_INSTRUCTIONS/_CLOUD_INSTRUCTIONS, _build_auth(), main()
├── identity.py    Token resolution — resolve_identity(ctx) → (user_id, get_token)
├── errors.py      translate_sdk_errors decorator — SDK domain exceptions → ToolError
└── tools/
    ├── billing.py         get_credit_balance
    ├── onboarding.py      get_github_install_url, index_repository, list_user_repositories
    ├── search/
    │   └── tools.py       search_repos, get_codebase_glossary
    ├── batch/
    │   ├── plan.py        propose_plan, replan, set_repo_subtask, add_repos, remove_repos
    │   ├── diff.py        start_diffs, chat_repo, wait_for_diffs
    │   ├── push.py        push_repos
    │   ├── pr.py          create_pr_prep, set_pr_prep, create_pr, update_pr, close_pr
    │   └── session.py     inspect_batch, cancel_batch
    └── github.py          get_workflow_runs, get_workflow_jobs
```

## Tool surface (25 local / 27 cloud)

`_BASE_TOOLS` (25, both modes) + `_ACCOUNT_TOOLS` (2, cloud only).

| Group | Tool | Annotation | Description |
|-------|------|-----------|-------------|
| Billing | `get_credit_balance` | readOnly | Current credit balance (**cloud only**) |
| Onboarding | `get_github_install_url` | readOnly | Direct GitHub App install link (**cloud only**) |
| Onboarding | `index_repository` | idempotent | Trigger indexing for a specific repo |
| Onboarding | `list_user_repositories` | readOnly | All linked repos with indexing status |
| Discovery | `search_repos` | readOnly | Structured filter and/or NL query — at least one required |
| Discovery | `get_codebase_glossary` | readOnly | User-specific terminology and query hints from codebase pass |
| Plan | `propose_plan` | idempotent | Start a batch — runs planner LLM; 409 if session exists |
| Plan | `replan` | — | Re-run planner with a hint; preserves session |
| Plan | `set_repo_subtask` | idempotent | Direct edit of one repo's description or base branch |
| Plan | `add_repos` | idempotent | Add repos mid-batch; runs planner per new repo |
| Plan | `remove_repos` | destructive | Wipe workspace + Redis keys for repos |
| Diff | `start_diffs` | idempotent | Kick off CLI for every pending repo; background |
| Diff | `chat_repo` | — | mode="qa" for Q&A; mode="edit" for code changes |
| Diff | `wait_for_diffs` | readOnly | MCP-side polling loop; streams progress; returns after ~25s |
| Push | `push_repos` | destructive | git push ready repos; `(repos, branch, force)` |
| PR | `create_pr_prep` | idempotent | Haiku-drafted title + body per repo; local only |
| PR | `set_pr_prep` | idempotent | Partial update of a repo's PR title or body |
| PR | `create_pr` | destructive | POST /pulls per repo; requires pr_prep and a successful push |
| PR | `update_pr` | — | PATCH /pulls/{n} on an already-open PR |
| PR | `close_pr` | destructive | Close PRs without merging |
| Session | `inspect_batch` | readOnly | `view="status"\|"pr_status"\|"diff_file"` — unified read tool |
| Session | `cancel_batch` | destructive | Cancel all in-flight tasks, wipe session + workspace |
| CI | `get_workflow_runs` | readOnly | One-shot CI status across repos — omit `repositories` to use session pushed repos |
| CI | `get_workflow_jobs` | readOnly | Per-job/step detail for a run; `failed_only=True` for triage |

## Viewing diffs without context pollution

`wait_for_diffs` returns only summaries per repo: `one_line_summary` + `file_stats` (paths, additions, deletions counts). The raw unified diff is **not** included.

To view the actual diff for a specific file, call:
```
inspect_batch(view="diff_file", repo="owner/repo", file="path/to/file")
```
Only call this when the user explicitly asks to see a file's diff — it returns the full unified diff and can be large.

## Call pattern inside tools

Every tool function:
1. Takes `ctx: Context` as first argument.
2. Calls `ws = ctx.lifespan_context["workspace"]` to get the process-level `Workspace`.
3. Calls `user_id, get_token = await resolve_identity(ctx)` to get the user identity.
4. Calls `ws.<method>(user_id, ...)` to invoke batch operations.
5. Raises `fastmcp.exceptions.ToolError` for user-facing errors (via `@translate_sdk_errors`).
6. Returns a Pydantic model — FastMCP exports its schema to Claude.

```python
# Typical pattern
@translate_sdk_errors
async def propose_plan(ctx: Context, query: str, repos: List[str]) -> PlanResponse:
    ws = ctx.lifespan_context["workspace"]
    user_id, get_token = await resolve_identity(ctx)
    return PlanResponse(session=await ws.propose(user_id, query, repos, get_token=get_token))
```

Search tools don't use the workspace — they call `IndexSearchService()` directly:
```python
user_id, _ = await resolve_identity(ctx)
svc = IndexSearchService()
result = svc.public_search_with_nl(user_id, ...)
```

## Authentication

`main.py` calls `_build_auth()` at startup:
- `LOCAL=true` (default): no auth, GITHUB_TOKEN used directly.
- `LOCAL=false`: `Auth0Provider` configured from `MCP_AUTH0_DOMAIN`, `MCP_AUTH0_CLIENT_ID`, `MCP_AUTH0_CLIENT_SECRET`, `MCP_AUTH0_AUDIENCE`. PKCE OAuth flow.

## Identity resolution

`identity.py` exposes `resolve_identity(ctx) -> Tuple[str, Callable[[], Awaitable[str]]]`:

```
resolve_identity(ctx) → (user_id, get_token)

  LOCAL mode:
    → user_id = "default", get_token = lambda: GITHUB_TOKEN

  Cloud mode:
    → ctx.get_state("resolved_user_id")  ← cache hit: skip JWT decode
    → cache miss:
        get_access_token() → JWT claims (sub, email, name)
        UserDB().resolve_or_create_from_auth0(sub, email, name) → user_id
        ctx.set_state("resolved_user_id", user_id)
    → get_token fetches GitHub App installation token on demand
```

## Error contract

`errors.py` provides `@translate_sdk_errors` decorator. All `SdkError` subclasses from `sdk/errors.py`:

| Exception | ToolError message |
|---|---|
| `GitHubAppNotInstalledError` | `"GitHub App is not installed. Install it at: <url>"` |
| `NotFoundError` | `"Not found: <detail>"` |
| `InvalidRequestError` | `"Invalid request: <detail>"` |
| `ConflictError` | `"<detail>"` (no prefix) |
| Any other `SdkError` | `"<detail>"` |

## Workspace and scheduler lifecycle

Both are constructed in `main()` and passed to `create_app`:

```python
cache = _build_cache()  # RedisCache or MemoryCache
workspace = Workspace(local=_LOCAL_MODE, base=_resolve_base(), cache=cache)
scheduler = IndexingScheduler(workspace)
app = create_app(..., workspace=workspace, scheduler=scheduler)
```

`_resolve_base()`:
- `LOCAL=true`: `Path.cwd()` at startup (user starts the server from their project root)
- `LOCAL=false`: `Path(os.getenv("WORKSPACE_BASE_DIR", "/var/workspaces"))`

Lifespan (`app.py`) yields `{"workspace": workspace, "scheduler": scheduler}` — tools access them via `ctx.lifespan_context["workspace"]` and `ctx.lifespan_context["scheduler"]`.

## Instructions (server system prompt)

Two instruction strings in `main.py`:
- `_LOCAL_INSTRUCTIONS` — minimal, assumes single user with GITHUB_TOKEN
- `_CLOUD_INSTRUCTIONS` — full conversational flow guide for multi-user cloud deployment

## Adding a new tool

1. Add the function to the appropriate `tools/*.py` module with `@translate_sdk_errors`.
2. Import and add it to `_BASE_TOOLS` or `_ACCOUNT_TOOLS` in `main.py`.
3. Add its annotation to `_TOOL_ANNOTATIONS` in `main.py`.

## Running locally

```bash
docker compose up -d --build mcp-server
```

### Smoke test (import check)

```bash
docker compose run --rm --no-deps mcp-server python3 -c "import mcp_server.main; print('OK')"
```
