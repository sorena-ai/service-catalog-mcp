import logging
from datetime import datetime
from typing import Any, Dict, Optional

import stripe

from api.db.users import UserDB

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    """Return a UTC ISO8601 timestamp with Z suffix."""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _default_subscription_snapshot() -> Dict[str, Any]:
    """Return a default snapshot for users without Stripe data."""
    return {
        "plan_name": "trial",
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "subscription_status": None,
        "subscription_current_period_end": None,
        "subscription_current_period_start": None,
        "subscription_plan_info": None,
        "synced_at": _utc_iso(),
    }


def load_subscription_snapshot(email: str, user_db: Optional[UserDB] = None) -> Dict[str, Any]:
    """Load the cached subscription snapshot for a user from MongoDB."""
    user_db = user_db or UserDB()
    db_user = user_db.get_user_by_email(email)

    if not db_user:
        logger.warning(f"User not found in database while loading subscription snapshot: {email}")
        return _default_subscription_snapshot()

    snapshot = {
        "plan_name": db_user.plan_name or "trial",
        "stripe_customer_id": db_user.stripe_customer_id,
        "stripe_subscription_id": db_user.stripe_subscription_id,
        "subscription_status": db_user.subscription_status,
        "subscription_current_period_end": db_user.subscription_current_period_end,
        "subscription_current_period_start": db_user.subscription_current_period_start,
        "subscription_plan_info": db_user.subscription_plan_info,
        "synced_at": _utc_iso(),
    }

    return snapshot


def _derive_plan_name(subscription_status: Optional[str], plan_info: Optional[Dict[str, Any]], current_plan: str) -> str:
    """Determine the canonical plan name based on subscription details."""
    active_statuses = {"active", "trialing"}
    if subscription_status in active_statuses and plan_info:
        for key in ("product_name", "nickname", "price_id"):
            value = plan_info.get(key)
            if isinstance(value, str) and value.strip():
                return value

    # Fall back to current plan if it already reflects a paid tier
    if subscription_status in active_statuses and current_plan and current_plan.strip().lower() != "trial":
        return current_plan

    return "trial"


def sync_user_subscription(email: str, user_db: Optional[UserDB] = None) -> Dict[str, Any]:
    """Fetch the latest Stripe subscription data and persist it in MongoDB."""
    user_db = user_db or UserDB()
    db_user = user_db.get_user_by_email(email)

    if not db_user:
        logger.warning(f"User not found in database while syncing subscription: {email}")
        return _default_subscription_snapshot()

    try:
        from api.stripe.client import get_stripe_client

        stripe_client = get_stripe_client()
        status = stripe_client.get_subscription_status(email)

        updates: Dict[str, Any]
        if not status:
            # No customer or subscriptions found
            updates = {
                "plan_name": "trial",
                "stripe_subscription_id": None,
                "subscription_status": None,
                "subscription_current_period_end": None,
                "subscription_current_period_start": None,
                "subscription_plan_info": None,
            }
        else:
            plan_info = status.get("plan_info") if isinstance(status.get("plan_info"), dict) else None
            subscription_status = status.get("status")
            plan_name = _derive_plan_name(subscription_status, plan_info, db_user.plan_name or "trial")

            updates = {
                "plan_name": plan_name,
                "stripe_customer_id": status.get("customer_id") or db_user.stripe_customer_id,
                "stripe_subscription_id": status.get("subscription_id"),
                "subscription_status": subscription_status,
                "subscription_current_period_end": status.get("current_period_end"),
                "subscription_current_period_start": status.get("current_period_start"),
                "subscription_plan_info": plan_info,
            }

            # When subscription is no longer active, normalise plan to trial
            inactive_statuses = {None, "canceled", "cancelled", "unpaid", "incomplete", "incomplete_expired", "past_due", "paused", "inactive"}
            if subscription_status in inactive_statuses or not status.get("subscription_id"):
                updates["plan_name"] = "trial"
                # Preserve plan info for historical display but only if present
                if plan_info is None:
                    updates["subscription_plan_info"] = None

        user_db.update_subscription_details(email, updates)

    except stripe.error.StripeError as error:
        logger.error(f"Stripe API error while syncing subscription for {email}: {error}", exc_info=True)
        return load_subscription_snapshot(email, user_db=user_db)
    except Exception as error:
        logger.error(f"Unexpected error syncing subscription for {email}: {error}", exc_info=True)
        return load_subscription_snapshot(email, user_db=user_db)

    return load_subscription_snapshot(email, user_db=user_db)


def get_user_plan_and_sync_stripe(email: str, user_db) -> str:
    """Backward-compatible helper returning the user's plan name after a sync."""
    snapshot = sync_user_subscription(email, user_db=user_db)
    return snapshot.get("plan_name", "trial")


def validate_email_format(email: Optional[str]) -> bool:
    """
    Validate email format using basic regex.

    Args:
        email: Email string to validate

    Returns:
        bool: True if email format is valid, False otherwise
    """
    if not email or not email.strip():
        return False

    import re
    # Basic email regex: something@something.something
    email_pattern = r'^[^@]+@[^@]+\.[^@]+$'
    return bool(re.match(email_pattern, email.strip()))
