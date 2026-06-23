# sdk/search — Repository Search

Query layer over the indexed data. Two surfaces: an agent-internal path with wide filters, and a public MCP path with a whitelist and hard caps.

## Files

```
search/
├── service.py     IndexSearchService — the single query entry point
├── models.py      output shapes (SearchResult, SearchResultNL, RepositoryMatch, …)
├── filters.py     filter shapes (AgentSearchFilters, PublicSearchFilters) + whitelists
└── nl_resolver.py NL query → PublicSearchFilters (LLM call)
```

## IndexSearchService (`service.py`)

Instantiated by callers (no global singleton). Constructor creates one DB accessor per collection:

```python
svc = IndexSearchService()
```

### Methods

| Method | Surface | Description |
|--------|---------|-------------|
| `search(user_id, filters, limit)` | agent | Structured filter → `dict` with `exact_matches`, `near_matches` (always empty today), `context_hits`, `not_found` |
| `public_search(user_id, filters, limit)` | MCP | Validates whitelist filters, calls `search`, returns `SearchResult` (narrowed shape, ≤5 evidence items per repo) |
| `public_search_with_nl(user_id, nl_query, limit)` | MCP | Resolves NL query via `nl_resolver`, calls `public_search`, augments with `context_hits` from text search |
| `get_repo_facts(user_id, repo)` | agent | Languages, workspaces, files, tree count, dependencies, extractions for one repo |
| `get_repo_contexts(user_id, repo, types, workspace)` | agent | `repository_contexts` rows for one repo |
| `search_repo_contexts_text(user_id, query, types, limit)` | both | Full-text search over `repository_contexts.content` |
| `get_repo_tree(user_id, repo)` | agent | Full path list + metadata for one repo |
| `get_codebase_glossary(user_id)` | MCP | `codebase_terminology` + `query_refinement_hints` contexts |
| `get_codebase_contexts(user_id, types)` | agent | All `codebase_contexts` rows for a user |
| `codebase_status(user_id)` | MCP | Latest `CodebaseRun` status |
| `dependency_impact(user_id, target)` | agent | Repos that depend on `target` via `repository_edges` |

**Result caps:** `PUBLIC_RESULT_CAP = 50`, `AGENT_RESULT_CAP = 200`.

### Filter narrowing (`_candidates_from_filters`)

Starts with `candidates = None` (no constraint). Each active filter calls the relevant DB accessor, converts to a `set[str]`, and intersects with `candidates`. All filters are AND-ed; `None` candidates means "match all". Evidence is tracked per repo per filter for the `exact_matches.evidence` list.

## Filters (`filters.py`)

**`AgentSearchFilters`** — agent-internal, `extra="ignore"`. Supports:
- `repository_names`, `dependency`, `language`, `framework`, `platform`
- `docker_image`, `github_action`, `has_file`, `workspace_manifest`
- `extraction` (raw dict: `{extraction_type, data}`) — direct access to the generic extractions collection

**`PublicSearchFilters`** — MCP-facing, `extra="forbid"`. Same fields except no `repository_names` and no `extraction`. `has_file` and `workspace_manifest` values are validated against:
- `PUBLIC_HAS_FILE_WHITELIST`: `Dockerfile`, `go.mod`, `package.json`, `pyproject.toml`, `Cargo.toml`, `Chart.yaml`, `main.tf`, `metadata.rb`, `Berksfile`, `docker-compose.yml`, `.github/workflows/*.yml`
- `PUBLIC_WORKSPACE_MANIFEST_WHITELIST`: `package.json`, `go.mod`, `pyproject.toml`, `Cargo.toml`, `Chart.yaml`, `main.tf`, `metadata.rb`

Whitelist validation happens in `IndexSearchService.public_search` (not in the Pydantic model).

## NL Resolver (`nl_resolver.py`)

`resolve_nl_query(user_id, nl_query, model?) -> (PublicSearchFilters, list[str])`

1. Loads `codebase_terminology` + `query_refinement_hints` from `CodebaseContextDB` as grounding
2. Builds a prompt with the query, canonical vocabulary lists, and the grounding
3. Calls `claude-haiku-4-5-20251001` (or `INDEX_NL_RESOLVER_MODEL` env override) synchronously
4. Parses the JSON response into `_ResolverOutput(filters, context_keywords)`
5. Enforces whitelists on the resolved filters; clips keywords to 5

Raises `NLResolverError` on any failure; the caller translates this to `InvalidRequestError`.

The resolver is a thin LLM classification call — it does not do text search itself. The returned `context_keywords` are passed to `search_repo_contexts_text` by `public_search_with_nl`.

## Output models (`models.py`)

| Model | Fields |
|-------|--------|
| `EvidenceItem` | `kind`, `path?` |
| `RepositoryMatch` | `repository_name`, `evidence: [EvidenceItem]` |
| `ContextHit` | `repository_name`, `context_type`, `snippet`, `tags`, `workspace_path?` |
| `SearchResult` | `exact_matches`, `near_matches`, `not_found` |
| `SearchResultNL` | `SearchResult` fields + `context_hits`, `resolved_filters`, `resolver_keywords` |
| `CodebaseGlossary` | `terminology`, `query_hints`, `has_glossary` |
