# sdk — Business Logic Layer

Shared Python package used by both `api` and `mcp_server`. Contains all domain logic; neither service has business logic of its own.

## Package layout

```
sdk/
├── batch/         batch change workflow (plan → diff → push → PR)
├── indexer/       repo indexing pipeline + scheduler
├── search/        structured + NL search over indexed data
├── storage/       Cache ABC (batch sessions) + DB abstractions (repositories)
├── errors.py      domain exceptions
└── vocabulary.py  Language / Framework / Platform enums
```

## Errors (`errors.py`)

All SDK-raised exceptions are protocol-neutral — no HTTP codes, no MCP types. The calling edge maps them:

| Exception | Meaning |
|-----------|---------|
| `NotFoundError` | resource does not exist |
| `ConflictError` | operation conflicts with current state or unmet precondition |
| `InvalidRequestError` | structurally invalid arguments |
| `GitHubAppNotInstalledError` | GitHub App not installed; carries `.install_url` |

`mcp_server/errors.py` translates these to `ToolError`. `api/` translates them to HTTP 4xx.

## Storage (`storage/`)

**Cache** (`storage/cache/`) — async ABC for batch session state keyed by `user_id`. Implementations: `RedisCache` (production) and `MemoryCache` (local/test). The batch workflow always accepts `cache: Cache` and `get_token: Callable` by dependency injection — never imports a global.

**DB** (`storage/db/mongo/`) — `UserRepositoryDB` is the primary DB accessor used by the indexer to read/write `user_repositories`.

## Vocabulary (`vocabulary.py`)

Defines the canonical string enums: `Language`, `Framework`, `Platform`, plus frozensets `LANGUAGES`, `FRAMEWORKS`, `PLATFORMS`. The search filters and NL resolver both import from here.

## Sub-package docs

Each sub-package has its own CLAUDE.md with deeper detail:

- [`batch/CLAUDE.md`](batch/CLAUDE.md)
- [`indexer/CLAUDE.md`](indexer/CLAUDE.md)
- [`search/CLAUDE.md`](search/CLAUDE.md)
