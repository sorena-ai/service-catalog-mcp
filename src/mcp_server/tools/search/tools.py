import logging
from typing import Optional

from fastmcp import Context
from fastmcp.exceptions import ToolError

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager
from sdk.search.filters import PublicSearchFilters
from sdk.search.models import CodebaseGlossary, SearchResultNL

log = logging.getLogger("mcp_server.search")


@translate_sdk_errors
async def search_repos(
    ctx: Context,
    filters: Optional[PublicSearchFilters] = None,
    nl_query: Optional[str] = None,
    limit: int = 20,
) -> SearchResultNL:
    """Find repositories matching a structured filter and/or a natural-language query.

    At least one of ``filters`` or ``nl_query`` must be provided.

    Use ``filters`` when the intent maps cleanly onto indexer facts:
        filters={"language": "go"}                  -> all Go repos
        filters={"framework": "fastapi"}             -> all FastAPI services
        filters={"docker_image": {"name": "postgres"}} -> repos pulling postgres
        filters={"has_file": "Dockerfile"}           -> repos with a Dockerfile

    Use ``nl_query`` for fuzzy or relational questions:
        nl_query="Which repos use Postgres but no migration tooling?"
        nl_query="Which services call the billing API?"

    Both can be combined to narrow results to repos that satisfy a filter
    AND match a prose description.
    """
    if filters is None and not nl_query:
        raise ToolError("Provide at least one of: filters, nl_query")
    sm = await get_service_manager(ctx)
    return sm.search_repos(filters=filters, nl_query=nl_query, limit=limit)


@translate_sdk_errors
async def get_codebase_glossary(ctx: Context) -> CodebaseGlossary:
    """Return user-specific terminology and query phrasing hints produced
    by the codebase pass.

    Call this before find_repos_by_query when the user's phrasing is
    ambiguous or uses internal project names — the hints steer the NL
    resolver toward matching values in the indexed vocabulary.
    """
    sm = await get_service_manager(ctx)
    return sm.get_codebase_glossary()
