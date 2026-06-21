# Service Catalog

AI-powered platform for making batch code changes across multiple GitHub repositories. Connect any MCP client, describe a change in plain English, and Service Catalog finds the right repos, generates diffs via Claude or Devin, pushes branches, and opens pull requests.

## Connect

### Hosted service

```bash
claude mcp add --transport http service-catalog-mcp https://mcp.infraas.ai
```

Or add manually to your MCP client config:

```json
{
  "mcpServers": {
    "service-catalog": {
      "url": "https://mcp.infraas.ai"
    }
  }
}
```

### Self-hosted

```bash
claude mcp add --transport http service-catalog-mcp http://localhost:8200
```

See [Self-hosting](#self-hosting) below to start the server locally.

## Self-hosting

### Prerequisites

- Docker and Docker Compose
- A GitHub [personal access token](https://github.com/settings/tokens) with `repo` scope
- An Anthropic API key **or** a Devin account

### 1. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set GITHUB_TOKEN and ANTHROPIC_API_KEY
```

### 2. Set up your CLI provider

Service Catalog generates code changes by running a CLI agent inside each cloned repository. Two providers are supported.

#### Claude (default)

Set in `.env`:

```
CLI_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

That's all — no other setup needed.

#### Devin

Devin authenticates via a credentials file on your host machine. Set it up once, then mount the file into the container so it persists across restarts.

**Step 1** — authenticate on your host:

```bash
# Install the Devin CLI if you haven't already
curl -fsSL https://cli.devin.ai/install.sh | bash

# Log in — this saves credentials to ~/.local/share/devin/credentials.toml
devin auth login --force-manual-token-flow
```

**Step 2** — mount the credentials file. Add this volume to the `mcp-server` service in `docker-compose.yml`:

```yaml
volumes:
  - ~/.local/share/devin/credentials.toml:/root/.local/share/devin/credentials.toml:ro
  - batch-workspaces:/var/batch-workspaces
  - repo-clones:/repos
```

**Step 3** — set in `.env`:

```
CLI_PROVIDER=devin
```

### 3. Start

```bash
docker compose up -d
```

The MCP server is available at `http://localhost:8200`.

### 4. Connect your MCP client

```bash
claude mcp add --transport http service-catalog-mcp http://localhost:8200
```

## How it works

A batch change follows four steps, each confirmed before moving to the next:

1. **Find repos** — `search_repos` finds repos by language, framework, dependency, or a plain-English query.
2. **Plan** — `propose_plan` calls the planner LLM and proposes a per-repo task; adjust with `replan` or `set_repo_subtask` before approving.
3. **Diff** — `start_diffs` runs the CLI agent in each repo; `wait_for_diffs` polls progress; review diffs with `chat_repo`.
4. **Push & PR** — `push_repos` pushes branches; `get_workflow_runs` shows CI; `create_pr` opens pull requests.

## Tools

### Discovery

| Tool | Description |
|------|-------------|
| `search_repos` | Search by dependency, language, framework, platform, GitHub Action, or NL query |
| `get_codebase_glossary` | Project-specific terminology and search hints |
| `list_repository_groups` | List saved repository groups |
| `get_repository_group` | Fetch a saved group by name |
| `list_user_repositories` | All linked repositories with indexing status |
| `index_repository` | Manually trigger indexing for a specific repo |

### Batch change

| Tool | Description |
|------|-------------|
| `propose_plan` | Start a batch — runs the planner and proposes per-repo tasks |
| `replan` | Re-run the planner with a hint |
| `set_repo_subtask` | Edit one repo's task description or base branch |
| `add_repos` | Add repos mid-batch |
| `remove_repos` | Remove repos from the current batch |
| `start_diffs` | Kick off the CLI agent for all pending repos |
| `wait_for_diffs` | Poll diff progress; streams updates, returns after ~25 s |
| `chat_repo` | Ask questions (`mode="qa"`) or request edits (`mode="edit"`) on a repo's diff |
| `inspect_batch` | View session status, PR status, or a specific file's diff |
| `push_repos` | Push branches for ready repos |
| `create_pr_prep` | Draft PR title and body for each repo |
| `set_pr_prep` | Edit a repo's PR title or body |
| `create_pr` | Open pull requests |
| `update_pr` | Edit an open PR |
| `close_pr` | Close PRs without merging |
| `cancel_batch` | Cancel all in-flight tasks and wipe the session |

### CI/CD

| Tool | Description |
|------|-------------|
| `get_workflow_runs` | GitHub Actions status across repos — call without args after `push_repos` to check all pushed repos |
| `get_workflow_jobs` | Per-job/step detail for a run; use `failed_only=True` for triage |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL` | `true` | `true` = single-user local mode; `false` = cloud mode (requires Auth0 + MongoDB) |
| `GITHUB_TOKEN` | — | Personal access token with `repo` scope (local mode) |
| `CLI_PROVIDER` | `claude` | Code-change agent: `claude` or `devin` |
| `ANTHROPIC_API_KEY` | — | Required when `CLI_PROVIDER=claude` |
| `CLAUDE_CLI_DEFAULT_MODEL` | — | Override the model used by the Claude CLI |
| `DEVIN_MODEL` | — | Override the model used by the Devin CLI |
| `MONGODB_URI` | — | MongoDB connection string (falls back to TinyDB if unset) |
| `MONGODB_DATABASE` | `service-catalog` | MongoDB database name |
| `REDIS_URL` | — | Redis URL (falls back to in-memory cache if unset) |
| `MCP_PORT` | `8200` | Port the MCP server listens on |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `LANGSMITH_API_KEY` | — | Enable LangSmith tracing (optional) |
| `CLONE_REPO_BASE_DIR` | `/repos` | Base directory for indexer clones |
| `BATCH_CLONE_BASE_DIR` | `/var/batch-workspaces` | Base directory for batch change workspaces |

Cloud-mode variables (`LOCAL=false`): `MCP_AUTH0_DOMAIN`, `MCP_AUTH0_CLIENT_ID`, `MCP_AUTH0_CLIENT_SECRET`, `MCP_AUTH0_AUDIENCE`, `MCP_BASE_URL`, `GITHUB_APP_ID`, `GITHUB_APP_NAME`, `GITHUB_PRIVATE_KEY_PATH`.

## License

MIT — see [LICENSE](LICENSE).
