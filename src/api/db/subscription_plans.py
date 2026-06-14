import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
from lib.db.mongo import MongoDB

# ---------------------------------------------------------------------------
# SubscriptionPlanDB (unchanged, no user identity involved)
# ---------------------------------------------------------------------------

class SubscriptionPlanDB:
    def __init__(self):
        self.db = MongoDB().connect()
        self.collection = self.db["subscription_plans"]
        try:
            self.collection.create_index("price_id", unique=True)
            self.collection.create_index("updated_at")
        except Exception as exc:
            logging.debug("Subscription plan index creation skipped: %s", exc)

    def get_recent_plans(self, max_age_minutes: int = 30) -> List[Dict[str, Any]]:
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        try:
            cached = list(self.collection.find({"updated_at": {"$gte": cutoff}}))
        except Exception as exc:
            logging.error("Error retrieving cached subscription plans: %s", exc)
            return []
        sanitized: List[Dict[str, Any]] = []
        for plan in cached:
            plan.pop("_id", None)
            if isinstance(plan.get("updated_at"), datetime):
                plan["updated_at"] = plan["updated_at"].isoformat()
            sanitized.append(plan)
        return sanitized

    def upsert_plans(self, plans: List[Dict[str, Any]]) -> None:
        if not plans:
            return
        now = datetime.utcnow()
        for plan in plans:
            try:
                self.collection.update_one(
                    {"price_id": plan.get("price_id")},
                    {"$set": {**plan, "updated_at": now}},
                    upsert=True,
                )
            except Exception as exc:
                logging.error("Error caching subscription plan %s: %s", plan.get("price_id"), exc)

    def purge_stale_plans(self, older_than_minutes: int = 1440) -> None:
        cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
        try:
            self.collection.delete_many({"updated_at": {"$lt": cutoff}})
        except Exception as exc:
            logging.error("Error purging stale subscription plans: %s", exc)
