import logging
from typing import Optional

from pydantic import BaseModel, EmailStr
from api.db.users import UserDB, User


class NewUserInput(BaseModel):
    auth0_sub: str
    email: EmailStr
    name: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    nickname: Optional[str] = None
    picture: Optional[str] = None
    email_verified: Optional[bool] = None
    updated_at: Optional[str] = None


def create_new(user_info: NewUserInput) -> User:
    """
    Create a new user record with initial credits but without Stripe customer.
    Stripe customer will be created when user first subscribes.

    Contract:
    - Returns the created `User` domain object as saved in MongoDB.
    - User gets initial credits without requiring Stripe integration.
    - stripe_customer_id will be None until first subscription.
    """

    # Prepare defaults - no Stripe customer creation during signup
    initial_credits: float = 2.0

    # Persist user in MongoDB via UserDB (Mongo-only logic)
    user_db = UserDB()
    enriched_info = {
        "auth0_sub": user_info.auth0_sub,
        "email": user_info.email,
        "name": user_info.name,
        "given_name": user_info.given_name,
        "family_name": user_info.family_name,
        "nickname": user_info.nickname,
        "picture": user_info.picture,
        "email_verified": user_info.email_verified,
        "updated_at": user_info.updated_at,
        "stripe_customer_id": None,  # Will be set when user first subscribes
        "credit_balance": initial_credits,
    }
    user = user_db.create_user(enriched_info)
    logging.info(
        f"Created new user: {user.email} with ${initial_credits:.2f} initial credits"
    )
    return user
