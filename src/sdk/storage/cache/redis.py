"""Redis-backed cache implementation."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import redis.asyncio as aioredis
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from sdk.batch.models import BatchSession, SubTask

from .base import Cache

_TTL = 4 * 3600
_TTL_PR = 24 * 3600


class _MetaBlob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    session_id: str
    query: str
    task: dict
    history: list
    created_at: datetime
    repos: list[str]


# -- key helpers ------------------------------------------------------------


def _meta_key(scope: str) -> str:
    return f"batch:session:{scope}:meta"


def _subtask_key(scope: str, repo: str) -> str:
    return f"batch:session:{scope}:subtask:{repo}"


def _raw_key(scope: str, repo: str, file: str) -> str:
    return f"batch:session:{scope}:raw:{repo}:{file}"


def _cli_key(scope: str, repo: str) -> str:
    return f"batch:session:{scope}:cli:{repo}"


def _bg_tasks_key(scope: str) -> str:
    return f"batch:session:{scope}:bg_tasks"


# -- implementation ---------------------------------------------------------


class RedisCache(Cache):
    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._redis = aioredis.from_url(url, decode_responses=True)

    async def get_session(self, scope: str) -> Optional[BatchSession]:
        from sdk.batch.models import BatchSession, SubTask

        raw = await self._redis.get(_meta_key(scope))
        if not raw:
            return None
        meta = _MetaBlob.model_validate_json(raw)
        if not meta.repos:
            sub_tasks = {}
        else:
            values = await self._redis.mget(
                *[_subtask_key(scope, r) for r in meta.repos]
            )
            sub_tasks = {}
            for repo, value in zip(meta.repos, values):
                if value:
                    try:
                        sub_tasks[repo] = SubTask.model_validate_json(value)
                    except Exception:
                        pass
        return BatchSession(
            user_id=meta.scope,
            session_id=meta.session_id,
            query=meta.query,
            task=meta.task,
            history=meta.history,
            created_at=meta.created_at,
            sub_tasks=sub_tasks,
        )

    async def set_meta(self, scope: str, session: BatchSession) -> None:
        blob = _MetaBlob(
            scope=scope,
            session_id=session.session_id,
            query=session.query,
            task=session.task.model_dump(),
            history=[h.model_dump() for h in session.history],
            created_at=session.created_at,
            repos=list(session.sub_tasks.keys()),
        )
        await self._redis.set(_meta_key(scope), blob.model_dump_json(), ex=_TTL)

    async def set_subtask(self, scope: str, repo: str, subtask: SubTask) -> None:
        ttl = _TTL_PR if subtask.pr is not None else _TTL
        pipe = self._redis.pipeline()
        pipe.set(_subtask_key(scope, repo), subtask.model_dump_json(), ex=ttl)
        if subtask.pr is not None:
            pipe.expire(_meta_key(scope), _TTL_PR)
        await pipe.execute()

    async def get_subtask(self, scope: str, repo: str) -> Optional[SubTask]:
        from sdk.batch.models import SubTask

        raw = await self._redis.get(_subtask_key(scope, repo))
        if not raw:
            return None
        return SubTask.model_validate_json(raw)

    async def delete_subtask(self, scope: str, repo: str) -> None:
        await self._redis.delete(_subtask_key(scope, repo))
        raw = await self._redis.get(_meta_key(scope))
        if raw:
            meta = _MetaBlob.model_validate_json(raw)
            if repo in meta.repos:
                meta.repos.remove(repo)
                await self._redis.set(
                    _meta_key(scope), meta.model_dump_json(), keepttl=True
                )

    async def set_raw_diff(self, scope: str, repo: str, file: str, diff: str) -> None:
        await self._redis.set(_raw_key(scope, repo, file), diff, ex=_TTL)

    async def set_raw_diff_many(
        self, scope: str, repo: str, diffs: dict[str, str]
    ) -> None:
        if not diffs:
            return
        pipe = self._redis.pipeline()
        for file, diff in diffs.items():
            pipe.set(_raw_key(scope, repo, file), diff, ex=_TTL)
        await pipe.execute()

    async def get_raw_diff(
        self, scope: str, repo: str, file: str
    ) -> Optional[str]:
        return await self._redis.get(_raw_key(scope, repo, file))

    async def set_cli_session(
        self, scope: str, repo: str, session_id: str, iteration: int
    ) -> None:
        payload = {
            "session_id": session_id,
            "iteration": iteration,
            "last_at": datetime.utcnow().isoformat(),
        }
        await self._redis.set(_cli_key(scope, repo), json.dumps(payload), ex=_TTL)

    async def get_cli_session(self, scope: str, repo: str) -> Optional[dict]:
        raw = await self._redis.get(_cli_key(scope, repo))
        if not raw:
            return None
        return json.loads(raw)

    async def register_bg_task(self, scope: str, name: str) -> None:
        await self._redis.sadd(_bg_tasks_key(scope), name)
        await self._redis.expire(_bg_tasks_key(scope), _TTL)

    async def unregister_bg_task(self, scope: str, name: str) -> None:
        await self._redis.srem(_bg_tasks_key(scope), name)

    async def get_bg_tasks(self, scope: str) -> list[str]:
        return list(await self._redis.smembers(_bg_tasks_key(scope)))

    async def wipe(self, scope: str) -> None:
        pattern = f"batch:session:{scope}:*"
        keys = [k async for k in self._redis.scan_iter(match=pattern)]
        if keys:
            await self._redis.delete(*keys)

    async def ping(self) -> bool:
        try:
            return await self._redis.ping()
        except Exception:
            return False
