# sdk/batch — Batch Change Workflow

Implements the full lifecycle for making coordinated code changes across multiple repos: plan → diff → push → PR.

## Phases and files

```
batch/
├── models.py     all Pydantic models (BatchSession, SubTask, DiffState, PushState, PR, …)
├── tasks.py      in-process asyncio.Task registry (user-level and per-repo)
├── workspace.py  on-disk clone directory layout
├── plan.py       plan phase: propose, replan, add/remove repos, set subtask
├── diff.py       diff phase: start_diffs, run_single_repo, chat_repo
├── push.py       push phase: push_repos, push_repo
├── pr.py         PR phase: create_pr_prep, set_pr_prep, create_pr, update_pr, close_pr
├── inspect.py    read-only views: status (concise/detailed), pr_status, diff_file
├── ci.py         CI status fetch (workflow runs + jobs)
└── llms/
    ├── planner.py    Sonnet structured-output call → Task + per-repo descriptions
    └── pr_drafter.py LLM-drafted PR title + body
```

`batch/__init__.py` re-exports every public symbol — callers `import sdk.batch` and use flat names.

## Data model

```
BatchSession
├── session_id, user_id, query, created_at
├── task: Task(description)         ← planner output, refined by replan
├── history: [Hint]                 ← user replan hints, appended chronologically
└── sub_tasks: dict[repo → SubTask]
        SubTask
        ├── repo, branch, description   ← set at propose / replan time
        ├── diff: DiffState?            ← set by start_diffs / chat_repo
        ├── push: PushState?            ← set by push_repos
        ├── pr_prep: PRPrep?            ← set by create_pr_prep / set_pr_prep
        └── pr: PR?                     ← set by create_pr
```

`DiffState.status` values: `pending → cloning → running → ready | failed`
`PushState.status` values: `pushing → pushed | failed`

## Session storage (Redis)

Sessions live in Redis (4-hour TTL) under `batch:session:{user_id}:*`. The `Cache` ABC (see `sdk/storage/cache/base.py`) defines the contract:

| Key suffix | Content |
|-----------|---------|
| `meta` | `BatchSession` without sub_tasks |
| `subtask:{owner/repo}` | `SubTask` for that repo |
| `cli:{owner/repo}` | CLI session ID + iteration |
| `raw:{owner/repo}:{file_path}` | raw unified diff per file |

`cache.get_session()` assembles meta + all subtasks into a full `BatchSession`.

## Workspace layout

Clones live at `{BATCH_CLONE_BASE_DIR}/{user_id}/{session_id}/{owner}__{repo}/` (default base: `/var/batch-workspaces`). These are ephemeral — not volume-mounted. They disappear on container restart or when `workspace.wipe_user()` / `wipe_repo_workspace()` is called.

`clone_repo()` is idempotent: if the directory exists it returns immediately (resume path).

## Plan phase (`plan.py`)

- **`propose(req, *, cache, get_token)`** — creates a new session (raises `ConflictError` if one already exists), resolves default branches, calls the planner LLM, writes meta + all subtasks to cache.
- **`replan(req, *, cache)`** — appends a `Hint` to history, re-runs the planner, updates task + subtask descriptions in-place (preserving diff/push/pr state).
- **`add_repos` / `remove_repos`** — mutate the subtask set; `remove_repos` cancels in-flight tasks and wipes workspaces.
- **`set_repo_subtask`** — override branch or description for one repo; branch change cancels its task and wipes its workspace.

## Diff phase (`diff.py`)

- **`start_diffs(req, *, cache, get_token)`** — for each pending repo, marks it `cloning`, fires a background task via `asyncio.create_task`, registers it in `tasks.py`.
- **`run_single_repo(...)`** — background coroutine: clone → mark `running` → run CLI → collect diff → write `ready` or `failed`. Uses `lib.cli.get_cli()`.
- **`chat_repo(repo, req, *, cache)`** — continues an existing CLI session. `mode="qa"` is read-only (no diff refresh). `mode="edit"` re-runs edits, increments `iteration`, refreshes `file_stats` and raw diffs.

`CliRefusal` exceptions are surfaced as `error_kind="external"` so the MCP tool can report them clearly.

## Push phase (`push.py`)

- **`push_repos(req, *, cache, get_token)`** — pushes all repos that are `diff.status == "ready"` and not yet pushed (or previously failed). Runs concurrently via `asyncio.gather`.
- **`push_repo(...)`** — stages all changes, creates/resets branch `service-catalog/batch-{session_id[:8]}`, commits as the `Service Catalog` bot actor, force-pushes to origin. GitHub token is embedded in the remote URL; scrubbed from error messages before logging.

## PR phase (`pr.py`)

- **`create_pr_prep(req, *, cache)`** — calls `llms.pr_drafter` for each repo with a ready diff to produce `PRPrep(title, body, head_branch, base_branch)`.
- **`set_pr_prep(repo, req, *, cache)`** — user edits to title/body.
- **`create_pr(req, *, cache, get_token)`** — re-pushes (idempotent), then opens the GitHub PR via `lib.github.prs.create_pull_request`.
- **`update_pr` / `close_pr`** — thin wrappers over `lib.github.prs` that also keep `pr_prep` in sync.

## CI phase (`ci.py`)

- **`get_ci_status(...)`** — fetches GitHub Actions workflow runs for pushed repos (by `pushed_sha`, PR head SHA, or branch). Writes `CIState` back into `PushState.ci` in the session. Returns `dict[repo → RepoCIResult]`.
- **`get_ci_jobs(user_id, repo, run_id, ...)`** — fetches jobs + steps for a single workflow run.

## Task registry (`tasks.py`)

In-process `asyncio.Task` registry at two levels:
- User-level (`_user_tasks`): for propose/replan tasks.
- Repo-level (`_repo_tasks`): for per-repo diff tasks.

`register_repo` cancels any prior task for the same `(user_id, repo)` key before registering the new one.

## LLMs

- **`llms/planner.py`** — `run_planner(session)`: async, uses `claude-sonnet-4-6` with a forced `set_plan` tool call to get `task_description` + `per_repo_descriptions`.
- **`llms/pr_drafter.py`** — `draft_pr(...)`: produces `PRDraftOutput(title, body)` used by `create_pr_prep`.

## Calling convention

All phase functions accept `cache: Cache` and (where needed) `get_token: Callable[[], Awaitable[str]]` as keyword-only arguments. They never import a global cache or token — callers (MCP tools) inject them. This keeps the batch package testable and host-agnostic.
