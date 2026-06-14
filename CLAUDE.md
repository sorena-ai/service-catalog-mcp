# CLAUDE.md

Service Catalog is an AI-powered platform for making batch code changes across multiple GitHub repositories.

Each service has its own CLAUDE.md with working details:

- [`src/mcp_server/CLAUDE.md`](src/mcp_server/CLAUDE.md) — FastMCP tool layer for Claude Desktop
- [`src/api/CLAUDE.md`](src/api/CLAUDE.md) — webhook-only FastAPI service

---

## System overview

```
                         Internet
                            │
                       Traefik (TLS)
                       ┌────┴────┐
                  Port 80/443   Port 8200
                     api        mcp-server
                  (webhooks)   (MCP tools)
                       │             │
                  src/ flat Python packages
                       │
                 MongoDB / Redis
```

**Routing rules:**
- GitHub/Stripe webhooks → Traefik → api
- Claude Desktop → Traefik → mcp-server

## Package layout

```
src/
├── Dockerfile        cloud image — api and mcp-server use it with different CMD
├── requirements.txt  consolidated deps
│
├── sdk/              business logic — shared by both services
│   ├── batch/        batch change workflow (plan, diff, push, PR)
│   ├── indexer/      repo indexing pipeline + scheduler
│   ├── search/       structured + NL search
│   ├── models/       shared Pydantic models
│   ├── storage/      cache (Redis/memory) + DB abstractions
│   ├── github/       GitHub actions, PRs, repos (uses SdkContext token)
│   ├── context.py    SdkContext — token getter + user scope (ContextVar)
│   ├── errors.py     SDK domain exceptions (GitHubAppNotInstalledError, etc.)
│   └── vocabulary.py language/framework/platform enums
│
├── lib/              low-level shared utilities
│   ├── async_utils.py  main-loop bridge (sync→async)
│   ├── claude_cli/     Claude CLI subprocess runner
│   ├── db/             MongoDB models and DB accessors (UserDB, UserRepositoryDB, etc.)
│   ├── github/         Low-level GitHub API client (installation tokens, etc.)
│   └── tracing/        LangSmith tracing helpers
│
├── api/              FastAPI service — GitHub callback+webhook, Stripe webhook, health
│   ├── auth/         JWT validation, GitHub install gate
│   ├── db/           API-specific DB accessors (UserDB, GithubUserDB, etc.)
│   ├── github/       GitHub App integration
│   ├── routes/       HTTP endpoints (github, stripe, health)
│   ├── stripe/       Stripe client and subscription service
│   └── users/        User management service
│
└── mcp_server/       FastMCP service — MCP tools for Claude Desktop
    ├── app.py        FastMCP factory (create_app, _ToolCallTracer middleware)
    ├── main.py       Entrypoint — LOCAL/cloud mode, tool list, instructions
    ├── identity.py   Token resolution + SdkContext wiring + session caching
    ├── errors.py     translate_sdk_errors decorator (SDK exceptions → ToolError)
    └── tools/        MCP tool functions (batch, billing, codebase_search, github, onboarding)
```

## Identity

| Mode | Identity carrier |
|------|-----------------|
| Cloud (LOCAL=false) | Auth0 JWT → `api.db.users.UserDB().resolve_or_create_from_auth0()` → `user_id` (cached in FastMCP session state) |
| Local (LOCAL=true) | `GITHUB_TOKEN` env var → `SdkContext` with `scope="default"` |

`user_id` (MongoDB `_id` as string) is the canonical identifier in cloud mode.

**SdkContext:** Every tool call installs a `SdkContext` ContextVar before invoking SDK code. In cloud mode the token getter fetches a GitHub App installation token on demand; in local mode it returns the static `GITHUB_TOKEN`.

**GitHub install gate:** `ensure_installed(user_id)` in `mcp_server/identity.py`. Raises `GitHubAppNotInstalledError`; `translate_sdk_errors` converts this to `ToolError` with the install URL.

## Data flows

**MCP tool call (batch):**
```
Claude Desktop → mcp-server: validate Auth0 JWT (cloud) or GITHUB_TOKEN (local)
  → resolve_user_id → install SdkContext ContextVar
  → tools/batch.py calls sdk.batch.service.propose(ProposeRequest(...)) directly
  ← BatchSession (plan ready)
Subsequent calls: replan, start_diffs, chat_repo, push_repos, create_pr, etc.
```

**GitHub install → indexing:**
```
User installs GitHub App
  → GitHub /callback → api/routes/github.py: link installation_id to user_id
  → GitHub /webhook → api/routes/github.py: ingest repos → trigger sdk.indexer.indexing_scheduler
    → run_indexing_event: clone → codebase pass → scan → repository pass → edges
```

## Data stores

### MongoDB collections

**Users/repos:**

| Collection | Purpose |
|-----------|---------|
| `users` | Profiles; `auth0_sub`, `installation_id`, `github_user_id`, billing fields |
| `github_users` | GitHub identity cache; links `github_user_id` → `user_id` |
| `user_repositories` | Per-user repos with `indexing_status` |

Access via `api/db/` (`UserDB`, `GithubUserDB`, `UserRepositoryDB`, etc.) or `lib/db/` for lower-level accessors.

**Indexer (owned by `sdk/indexer/`):**

| Collection | Purpose |
|-----------|---------|
| `repository_files` | Curated important files with role and purpose |
| `repository_trees` | Full path list per repo |
| `repository_workspaces` | Monorepo workspace roots |
| `repository_languages` | Language detections |
| `repository_dependencies` | Per-package-manager dependency rows |
| `repository_extractions` | Generic sparse facts |
| `repository_contexts` | per-repo LLM-generated context sections |
| `repository_edges` | Cross-repo relationships |
| `repository_groups` | User-owned named repo sets |
| `codebase_contexts` | codebase-wide LLM output per user |
| `codebase_runs` | codebase pass run metadata |
| `indexing_event_runs` | End-to-end indexing event records |

### Redis batch sessions

Batch sessions live in Redis under `batch:session:{user_id}:*` with a 4-hour TTL.

Key structure per session:
- `batch:session:{user_id}:meta` — session metadata + planner task
- `batch:session:{user_id}:subtask:{owner/repo}` — per-repo state (diff, push, PR)
- `batch:session:{user_id}:cli:{owner/repo}` — CLI runner state
- `batch:session:{user_id}:raw:{owner/repo}:{file_path}` — raw unified diff per file

### Repo workspaces (disk)

**Two separate directories — do not confuse them:**

| Purpose | Env var | Default | Host mount |
|---------|---------|---------|------------|
| Batch change clones | `BATCH_CLONE_BASE_DIR` | `/var/batch-workspaces` | none (ephemeral) |
| Indexer clones | `CLONE_REPO_BASE_DIR` | `/repos` | `./data/repodb` |

Batch workspace path: `{BATCH_CLONE_BASE_DIR}/{user_id}/{session_id}/{owner}__{repo}/`

Batch workspaces are not volume-mounted — they live only in the container for the lifetime of the session. When `cancel_batch` is called (or the container restarts), they are gone.

## Running everything

```bash
docker compose up -d --build
```

Available: `api`, `mcp-server`, `mongodb`, `mongo-express`, `redis`, `traefik`

**Local URLs:**
- API: https://localhost.api.infraas.ai
- MCP server: http://localhost:8200
- Mongo Express: http://localhost:8081

## Environment variables

**Mode:** `LOCAL=true` (default) — single-user local mode. `LOCAL=false` — cloud mode, requires Auth0 + MongoDB.

**Auth0 (cloud MCP):** `MCP_AUTH0_DOMAIN`, `MCP_AUTH0_CLIENT_ID`, `MCP_AUTH0_CLIENT_SECRET`, `MCP_AUTH0_AUDIENCE`

**GitHub (local MCP):** `GITHUB_TOKEN` — personal access token used as the single identity.

**LLM APIs:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `VOYAGEAI_API_KEY`

**GitHub App (cloud):** `GITHUB_PRIVATE_KEY_PATH` (`/data/service-catalog.pem`), `GITHUB_APP_ID`, `GITHUB_APP_NAME`

**Databases:** `MONGODB_URI`, `MONGODB_DATABASE`, `REDIS_URL`

**Stripe:** `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`

**Workspaces:** `CLONE_REPO_BASE_DIR` — base dir for cloned repos (default `/repos` in container)
