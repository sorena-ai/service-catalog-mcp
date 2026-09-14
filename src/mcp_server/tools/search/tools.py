import logging
from typing import Optional

from fastmcp import Context
from fastmcp.exceptions import ToolError

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import resolve_identity
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
    user_id, _ = await resolve_identity(ctx)
    from sdk.search.service import IndexSearchService
    svc = IndexSearchService()
    if nl_query:
        return svc.public_search_with_nl(user_id, nl_query, limit=limit)
    result = svc.public_search(user_id, filters, limit=limit)
    return SearchResultNL(
        exact_matches=result.exact_matches,
        near_matches=result.near_matches,
        not_found=result.not_found,
    )


@translate_sdk_errors
async def get_codebase_glossary(ctx: Context) -> CodebaseGlossary:
    """Return user-specific terminology and query phrasing hints produced
    by the codebase pass.

    Call this before find_repos_by_query when the user's phrasing is
    ambiguous or uses internal project names — the hints steer the NL
    resolver toward matching values in the indexed vocabulary.
    """
    user_id, _ = await resolve_identity(ctx)
    from sdk.search.service import IndexSearchService
    return IndexSearchService().get_codebase_glossary(user_id)
