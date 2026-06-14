import logging
from typing import Dict, Any, Optional
from datetime import datetime
from lib.db.mongo import MongoDB

class GithubUser:
    """GitHub identity cache — _id is github_user_id (int)."""

    def __init__(
        self,
        github_user_id: int,
        login: str,
        user_id: str,
        installation_id: int,
        name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self._id = github_user_id
        self.login = login
        self.name = name
        self.avatar_url = avatar_url
        self.installation_id = installation_id
        self.user_id = user_id
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "_id": self._id,
            "login": self.login,
            "name": self.name,
            "avatar_url": self.avatar_url,
            "installation_id": self.installation_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GithubUser":
        return cls(
            github_user_id=data["_id"],
            login=data.get("login", ""),
            name=data.get("name"),
            avatar_url=data.get("avatar_url"),
            installation_id=data.get("installation_id", 0),
            user_id=data.get("user_id", ""),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ---------------------------------------------------------------------------
# GithubUserDB
# ---------------------------------------------------------------------------

class GithubUserDB:
    def __init__(self):
        self.mongo = MongoDB()
        self.collection = self.mongo.get_collection("github_users")

    def upsert(self, github_user: GithubUser) -> None:
        try:
            doc = github_user.to_dict()
            self.collection.update_one(
                {"_id": github_user._id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as e:
            logging.error("Error upserting github_user: %s", e)
            raise

    def get_by_installation_id(self, installation_id: int) -> Optional[GithubUser]:
        try:
            data = self.collection.find_one({"installation_id": installation_id})
            return GithubUser.from_dict(data) if data else None
        except Exception as e:
            logging.error("Error getting github_user by installation_id: %s", e)
            raise

    def get_by_user_id(self, user_id: str) -> Optional[GithubUser]:
        try:
            data = self.collection.find_one({"user_id": user_id})
            return GithubUser.from_dict(data) if data else None
        except Exception as e:
            logging.error("Error getting github_user by user_id: %s", e)
            raise

