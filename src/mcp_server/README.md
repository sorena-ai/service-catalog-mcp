# Service Catalog MCP Server

FastMCP server that lets Claude Desktop drive the batch change workflow across GitHub repositories.

## Connecting Claude Desktop

Add to your MCP client config (Claude Desktop, opencode, etc.):

```json
{
  "mcpServers": {
    "service-catalog": {
      "url": "https://mcp.infraas.ai/mcp"
    }
  }
}
```

For local dev: `"url": "http://localhost:8200/mcp"` (port 8200 is exposed directly to the host).

## Authentication

The server uses Auth0 OAuth (PKCE flow). On first connection your MCP client will open a browser for login. After login the session token is cached for subsequent requests.

Set `MCP_AUTH0_DOMAIN=""` in your environment to skip authentication in local dev.

## Tools

### Onboarding

| Tool | Description |
|------|-------------|
| `get_github_install_url` | Get the GitHub App installation URL |
| `get_onboarding_status` | Check GitHub App install + initial indexing state |
| `get_indexing_status` | Check indexing progress for all repositories |
| `index_repository` | Manually trigger indexing for a specific repository |
| `list_user_repositories` | List repositories (optionally `indexed_only=true`) |

### Codebase search

| Tool | Description |
|------|-------------|
| `query_user_codebase` | Search repos by dependency, framework, language, platform, docker image, GitHub action, file presence, or NL query |
| `list_repository_groups` | List saved repository groups |
| `get_repository_group` | Get a named repository group |

### Billing

| Tool | Description |
|------|-------------|
| `get_credit_balance` | Get current credit balance and plan info |

### Batch lifecycle

| Tool | Description |
|------|-------------|
| `start_batch_change` | Start a new batch change session (optional `repos` list; requires confirmation) |
| `get_batch_change_status` | Get full session state |
| `cancel_batch_change` | Cancel and wipe the current session |

### Step 1 — Candidate repos

| Tool | Description |
|------|-------------|
| `get_step1_candidate_repos` | List current candidate repositories |
| `set_step1_query` | Update the batch query (cascades to diffs) |
| `add_step1_repo` | Add a repository to the candidate list |
| `remove_step1_repo` | Remove a repository from the candidate list |
| `set_step1_repo_selected` | Mark a repo as selected or deselected |
| `set_step1_repo_head_branch` | Set the target branch for a repo |
| `approve_step1` | Approve Step 1 and kick off diff generation |

### Step 2 — Diff review

| Tool | Description |
|------|-------------|
| `get_step2_status` | Per-repo diff job statuses and file stats |
| `get_step2_repo_summary` | File-level stats for one repo (LLM-safe) |
| `get_step2_repo_explanation` | NL summary of changes for one repo (LLM-safe) |
| `get_step2_repo_diff` | Raw paginated diff for one file (`file_path` required) |
| `approve_step2` | Approve Step 2 and generate PR previews |

### Step 3 — PR previews

| Tool | Description |
|------|-------------|
| `get_step3_pr_previews` | All PR previews |
| `patch_step3_defaults` | Apply default title/body/branch to all non-overridden previews |
| `update_step3_repo_title` | Set PR title for one repo |
| `update_step3_repo_body` | Set PR body for one repo |
| `update_step3_repo_head_branch` | Set head branch for one repo |
| `update_step3_repo_base_branch` | Set base branch for one repo |
| `update_step3_repo_commit_message` | Set commit message for one repo |
| `set_step3_repo_selected` | Include or exclude one repo from PR creation |
| `approve_step3` | Approve Step 3 and kick off PR creation |

### Step 4 — PR creation

| Tool | Description |
|------|-------------|
| `get_step4_task_status` | PR creation task status and results |
| `get_step4_pull_requests` | List of created pull requests |
| `save_batch_as_task` | Persist the completed batch as a saved task |

## Typical session

```
You: "Update the logging library across all my Go repos"
→ start_batch_change(query="Update the logging library...")
← Session created; use get_step1_candidate_repos to see suggestions

You: review and approve repos
→ approve_step1()
← Diff jobs enqueued; poll get_step2_status

You: review diffs
→ get_step2_repo_explanation(repo_name="owner/repo")
→ approve_step2()
← PR previews generated

You: edit and approve PRs
→ patch_step3_defaults(title="chore: upgrade logger")
→ approve_step3()
← PRs being created

You: check results
→ get_step4_task_status()
→ save_batch_as_task()
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CORE_BASE_URL` | `http://core:8400` | Internal core service URL |
| `MCP_PORT` | `8200` | Port the server listens on |
| `MCP_AUTH0_DOMAIN` | — | Auth0 tenant domain |
| `MCP_AUTH0_CLIENT_ID` | — | Auth0 client ID |
| `MCP_AUTH0_CLIENT_SECRET` | — | Auth0 client secret |
| `MCP_AUTH0_AUDIENCE` | — | Auth0 audience |
| `MCP_BASE_URL` | `http://localhost:8200` | Public base URL (used in OAuth redirects) |
