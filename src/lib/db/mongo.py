import os
from pymongo import MongoClient
from pymongo.collection import Collection


class MongoDB:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.client = None
            cls._instance.db = None
        return cls._instance

    def connect(self):
        mongo_uri = os.getenv("MONGODB_URI", "")
        db_name = os.getenv("MONGODB_DATABASE", "")
        if not mongo_uri:
            raise ValueError("MONGODB_URI environment variable is required")
        if not db_name:
            raise ValueError("MONGODB_DATABASE environment variable is required")
        if not self.client:
            self.client = MongoClient(mongo_uri)
            self.db = self.client[db_name]
        return self.db

    def get_collection(self, collection_name: str) -> Collection:
        if self.db is None:
            self.connect()
        return self.db[collection_name]

