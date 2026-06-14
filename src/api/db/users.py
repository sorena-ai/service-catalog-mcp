import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from bson import ObjectId
from lib.db.mongo import MongoDB

# ---------------------------------------------------------------------------
# User model — canonical identity is _id (user_id); auth0_sub links to Auth0
# ---------------------------------------------------------------------------

class User:
    def __init__(
        self,
        auth0_sub: Optional[str] = None,
        name: Optional[str] = None,
        email: Optional[str] = None,
        github_user_id: Optional[int] = None,
        installation_id: Optional[int] = None,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
        subscription_status: Optional[str] = None,
        subscription_current_period_end: Optional[int] = None,
        subscription_current_period_start: Optional[int] = None,
        subscription_plan_info: Optional[Dict[str, Any]] = None,
        credit_balance: float = 0.0,
        plan_name: str = "trial",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        _id: Optional[Any] = None,
    ):
        self._id = _id
        self.auth0_sub = auth0_sub
        self.name = name
        self.email = email
        self.github_user_id = github_user_id
        self.installation_id = installation_id
        self.stripe_customer_id = stripe_customer_id
        self.stripe_subscription_id = stripe_subscription_id
        self.subscription_status = subscription_status
        self.subscription_current_period_end = subscription_current_period_end
        self.subscription_current_period_start = subscription_current_period_start
        self.subscription_plan_info = subscription_plan_info
        self.credit_balance = credit_balance if credit_balance is not None else 0.0
        self.plan_name = plan_name if plan_name is not None else "trial"
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    @property
    def user_id(self) -> Optional[str]:
        return str(self._id) if self._id else None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "auth0_sub": self.auth0_sub,
            "name": self.name,
            "email": self.email,
            "github_user_id": self.github_user_id,
            "installation_id": self.installation_id,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "subscription_status": self.subscription_status,
            "subscription_current_period_end": self.subscription_current_period_end,
            "subscription_current_period_start": self.subscription_current_period_start,
            "subscription_plan_info": self.subscription_plan_info,
            "credit_balance": self.credit_balance,
            "plan_name": self.plan_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self._id:
            data["_id"] = self._id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        return cls(
            _id=data.get("_id"),
            auth0_sub=data.get("auth0_sub"),
            name=data.get("name"),
            email=data.get("email"),
            github_user_id=data.get("github_user_id"),
            installation_id=data.get("installation_id"),
            stripe_customer_id=data.get("stripe_customer_id"),
            stripe_subscription_id=data.get("stripe_subscription_id"),
            subscription_status=data.get("subscription_status"),
            subscription_current_period_end=data.get("subscription_current_period_end"),
            subscription_current_period_start=data.get("subscription_current_period_start"),
            subscription_plan_info=data.get("subscription_plan_info"),
            credit_balance=data.get("credit_balance", 0.0),
            plan_name=data.get("plan_name", "trial"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ---------------------------------------------------------------------------
# UserDB
# ---------------------------------------------------------------------------

class UserDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("users")

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        try:
            data = self.collection.find_one({"_id": ObjectId(user_id)})
            return User.from_dict(data) if data else None
        except Exception as e:
            logging.error("Error getting user by id: %s", e)
            raise

    def get_user_by_auth0_sub(self, auth0_sub: str) -> Optional[User]:
        """Look up a user by their Auth0 subject claim.

        Matches on the canonical `auth0_sub` field, falling back to the legacy
        `sub` field used by older records (pre-rename). When a legacy record is
        found, the field is migrated in place: `sub` → `auth0_sub`, so the next
        lookup hits the canonical field directly.
        """
        try:
            data = self.collection.find_one(
                {"$or": [{"auth0_sub": auth0_sub}, {"sub": auth0_sub}]}
            )
            if not data:
                return None
            if data.get("auth0_sub") is None and data.get("sub") == auth0_sub:
                self.collection.update_one(
                    {"_id": data["_id"]},
                    {
                        "$set": {"auth0_sub": auth0_sub, "updated_at": datetime.utcnow()},
                        "$unset": {"sub": ""},
                    },
                )
                data["auth0_sub"] = auth0_sub
                data.pop("sub", None)
                logging.info("Migrated legacy `sub` → `auth0_sub` for user %s", data.get("_id"))
            return User.from_dict(data)
        except Exception as e:
            logging.error("Error getting user by auth0_sub: %s", e)
            raise

    def get_user_by_installation_id(self, installation_id: int) -> Optional[User]:
        try:
            data = self.collection.find_one({"installation_id": installation_id})
            return User.from_dict(data) if data else None
        except Exception as e:
            logging.error("Error getting user by installation_id: %s", e)
            raise

    def create_from_auth0(self, auth0_sub: str, email: Optional[str] = None, name: Optional[str] = None) -> User:
        try:
            user = User(auth0_sub=auth0_sub, email=email, name=name)
            result = self.collection.insert_one(user.to_dict())
            user._id = result.inserted_id
            logging.info("Created user %s for auth0_sub %s", user.user_id, auth0_sub)
            return user
        except Exception as e:
            logging.error("Error creating user from auth0: %s", e)
            raise

    def resolve_or_create_from_auth0(self, auth0_sub: str, email: Optional[str] = None, name: Optional[str] = None) -> Tuple[User, bool]:
        """Return (user, is_new). Creates a new user if none exists for this auth0_sub."""
        existing = self.get_user_by_auth0_sub(auth0_sub)
        if existing:
            return existing, False
        return self.create_from_auth0(auth0_sub, email=email, name=name), True

    def link_github_installation(
        self,
        user_id: str,
        installation_id: int,
        github_user_id: Optional[int] = None,
    ) -> bool:
        try:
            update: Dict[str, Any] = {
                "installation_id": installation_id,
                "updated_at": datetime.utcnow(),
            }
            if github_user_id is not None:
                update["github_user_id"] = github_user_id
            result = self.collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update},
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error("Error linking github installation: %s", e)
            raise

    def remove_installation(self, installation_id: int) -> bool:
        try:
            result = self.collection.update_one(
                {"installation_id": installation_id},
                {"$unset": {"installation_id": "", "github_user_id": ""}, "$set": {"updated_at": datetime.utcnow()}},
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error("Error removing installation: %s", e)
            raise

    # --- billing helpers (keyed by user_id) ---

    def get_credit_balance(self, user_id: str) -> float:
        user = self.get_user_by_id(user_id)
        return user.credit_balance if user else 0.0

    def update_credit_balance(self, user_id: str, new_balance: float) -> bool:
        try:
            result = self.collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"credit_balance": new_balance, "updated_at": datetime.utcnow()}},
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error("Error updating credit balance: %s", e)
            raise

    def deduct_credits(self, user_id: str, amount: float) -> bool:
        balance = self.get_credit_balance(user_id)
        return self.update_credit_balance(user_id, balance - amount)

    def add_credits(self, user_id: str, amount: float) -> bool:
        balance = self.get_credit_balance(user_id)
        return self.update_credit_balance(user_id, balance + amount)

    def update_subscription_details(self, user_id: str, details: Dict[str, Any]) -> bool:
        try:
            if not details:
                return False
            set_fields: Dict[str, Any] = {}
            unset_fields: Dict[str, str] = {}
            for key, value in details.items():
                if value is None:
                    unset_fields[key] = ""
                else:
                    set_fields[key] = value
            set_fields["updated_at"] = datetime.utcnow()
            payload: Dict[str, Any] = {}
            if set_fields:
                payload["$set"] = set_fields
            if unset_fields:
                payload["$unset"] = unset_fields
            result = self.collection.update_one({"_id": ObjectId(user_id)}, payload)
            return result.matched_count > 0
        except Exception as e:
            logging.error("Error updating subscription details: %s", e)
            raise

    def update_stripe_customer_id(self, user_id: str, stripe_customer_id: str) -> bool:
        try:
            result = self.collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"stripe_customer_id": stripe_customer_id, "updated_at": datetime.utcnow()}},
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error("Error updating stripe customer id: %s", e)
            raise

