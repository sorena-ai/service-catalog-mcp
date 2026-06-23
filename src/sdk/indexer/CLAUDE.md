# sdk/indexer — Repository Indexing Pipeline

Indexes GitHub repositories into MongoDB so the search layer can query them. Entry points are `run_indexing_event` (one-shot) and `IndexingScheduler` (per-user basket with a background worker).

## File layout

```
indexer/
├── orchestrator.py          run_indexing_event — 6-step pipeline
├── scheduler.py             IndexingScheduler — basket + worker per user
├── clone_workspace.py       IndexCloneWorkspace — per-event clone directory
├── progress.py              in-memory progress tracker (SSE feed)
├── relationships.py         build_edges / persist_edges — cross-repo dependency graph
├── _walker.py               walk_repo — yields (path, content) pairs ignoring noise
├── lang_extensions.py       file-extension → Language mapping
│
├── workspace_analyzer/      codebase pass (multi-repo LLM analysis)
│   ├── analysis.py          run_workspace_analysis — calls Claude CLI
│   ├── assembler.py         build prompt from repo cards
│   ├── parser.py            parse LLM JSON output → CodebaseContext rows
│   └── scanners/
│       ├── languages.py     scan_languages
│       ├── tree.py          scan_tree
│       └── workspaces.py    scan_workspaces
│
├── repo_analyzer/           repository pass (per-repo LLM context generation)
│   ├── analysis.py          run_repo_analysis — calls Claude CLI
│   └── scanners/
│       ├── files.py         scan_files (curated important files)
│       ├── dependencies.py  scan_dependencies (per package manager)
│       └── extractions/     deterministic fact extraction
│           ├── docker.py    Docker images + compose
│           ├── github_actions.py  GH Actions used
│           ├── helm.py      Helm chart metadata
│           ├── chef.py      Chef cookbook metadata
│           ├── kubernetes.py  K8s manifests
│           ├── terraform.py Terraform modules
│           ├── frameworks.py  framework detection from deps
│           └── platforms.py  platform detection from tree + extractions
│
└── db/                      MongoDB accessors (one per collection)
    ├── base.py
    ├── codebase_contexts.py
    ├── codebase_runs.py
    ├── contexts.py
    ├── dependencies.py
    ├── edges.py
    ├── extractions.py
    ├── files.py
    ├── languages.py
    ├── runs.py
    ├── tree.py
    └── workspaces.py
```

## Pipeline (`orchestrator.py`)

`run_indexing_event(user_id, repository_names, token_provider, trigger)` runs end-to-end and returns the `IndexEventRun` id:

1. **Insert** `IndexEventRun` (status=running) + call `progress.begin_event`
2. **Clone** all repos in parallel into `IndexCloneWorkspace` (shallow, depth=1)
3. **Codebase pass** — `run_workspace_analysis`: loads existing repo cards for already-indexed repos, runs the workspace analyzer (Claude CLI) over new ones, writes `codebase_contexts` + `codebase_runs`
4. **Scan** each repo in parallel — `_scan_and_persist_one`: tree, languages, files, workspaces, dependencies, all extraction scanners. Writes into all `repository_*` collections. Per-repo scanner errors are logged and skipped; other repos continue.
5. **Repository pass** — `run_repo_analysis`: runs a second Claude CLI pass per repo with codebase contexts as grounding, writes `repository_contexts`
6. **Edges** — `build_edges` + `persist_edges`: cross-repo dependency graph from `repository_dependencies`
7. **Mark** repos as `indexed` in `user_repositories`; finalize `IndexEventRun`; cleanup clone workspace

Codebase pass or repository pass failures abort the event (the `except` block marks the run `failed`). Per-repo scanner failures are non-fatal.

## Scheduler (`scheduler.py`)

`IndexingScheduler` — module-level singleton `indexing_scheduler`, used by `api/` on webhook events.

- One basket (`set[str]`) and one background worker (`asyncio.Task`) per user.
- `trigger(user_id, repos, token_provider, trigger)`: adds repos to the basket, starts a worker if one isn't running. If a worker is running, it will pick up the new repos when it next drains.
- **`AUTO_INDEX_BULK_LIMIT = 5`**: if `bulk_limit=True` (default) and `len(repos) > 5`, the trigger is skipped to avoid runaway indexing on large installs.
- Worker drains the basket in a loop until empty — repos added mid-run are processed in the next back-to-back event, not folded into the current one.
- The basket is in-memory; process restarts lose pending repos (they stay `pending` in Mongo until re-triggered).

## Clone workspace (`clone_workspace.py`)

`IndexCloneWorkspace(user_id)` manages a temporary directory structure:
```
{CLONE_REPO_BASE_DIR}/{user_id}/{event_id}/{owner}__{repo}/
```
Default base: `/repos` (env `CLONE_REPO_BASE_DIR`). Volume-mounted on `./data/repodb` in docker-compose. `cleanup(event_id)` removes the event directory after the pipeline finishes.

Do not confuse with batch workspaces (`BATCH_CLONE_BASE_DIR` / `/var/batch-workspaces`) — those are separate.

## Progress tracking (`progress.py`)

In-memory event + per-repo progress state, consumed by SSE endpoints in `api/`. Functions: `begin_event`, `set_phase`, `set_repo_step`, `mark_repo_done`, `mark_repo_failed`, `complete_event`, `fail_event`.

## Extraction scanners

All scanners under `repo_analyzer/scanners/extractions/` return lists of `RepositoryExtraction` objects. The orchestrator calls each scanner only when the relevant file types are present (e.g. `_has_docker(paths)` gate). Results are grouped by `extraction_type` and upserted via `RepositoryExtractionDB.replace_for_repository_type`.

`scan_platforms_from_tree` runs last — it derives platform tags (e.g. `docker`, `kubernetes`, `terraform`) from the tree structure and earlier extractions.

## Cross-repo edges (`relationships.py`)

`build_edges(user_id, repos)` reads `repository_dependencies` for the given repos and finds internal cross-repo references. `persist_edges` upserts into `repository_edges`. Used by `IndexSearchService.dependency_impact`.

## MongoDB collections owned here

| Collection | DB accessor |
|-----------|------------|
| `repository_files` | `RepositoryFileDB` |
| `repository_trees` | `RepositoryTreeDB` |
| `repository_workspaces` | `RepositoryWorkspaceDB` |
| `repository_languages` | `RepositoryLanguageDB` |
| `repository_dependencies` | `RepositoryDependencyDB` |
| `repository_extractions` | `RepositoryExtractionDB` |
| `repository_contexts` | `RepositoryContextDB` |
| `repository_edges` | `RepositoryEdgeDB` |
| `codebase_contexts` | `CodebaseContextDB` |
| `codebase_runs` | `CodebaseRunDB` |
| `indexing_event_runs` | `IndexEventRunDB` |
