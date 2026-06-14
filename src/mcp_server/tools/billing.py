"""Billing and credit balance tools."""

from fastmcp import Context
from fastmcp.exceptions import ToolError

from mcp_server.errors import translate_sdk_errors
from mcp_server.identity import get_service_manager
from api.db.users import UserDB


@translate_sdk_errors
async def get_credit_balance(ctx: Context) -> dict:
    """Get the user's current AI credit balance (in USD).

    Returns credit_balance (float), plan_name, and subscription_status. Use
    this when the user asks how much credit they have left, or before
    suggesting an operation that will consume credits.

    No GitHub installation is required — this works as soon as the user is
    authenticated.
    """
    sm = await get_service_manager(ctx)
    user = UserDB().get_user_by_id(sm.user_id)
    if not user:
        raise ToolError("Not found: User not found")
    return {
        "user_id": user.user_id,
        "credit_balance": float(user.credit_balance or 0.0),
        "plan_name": user.plan_name,
        "subscription_status": user.subscription_status,
    }
