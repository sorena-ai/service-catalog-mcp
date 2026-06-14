"""In-process memory cache — no external dependencies."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sdk.batch.models import BatchSession, SubTask

from .base import Cache

_TTL = 4 * 3600
_TTL_PR = 24 * 3600


def _now_ts() -> float:
    return time.monotonic()


class MemoryCache(Cache):
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, object]] = {}
        self._bg_tasks: dict[str, set[str]] = {}

    # -- helpers ---------------------------------------------------------

    def _get(self, key: str) -> object | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < _now_ts():
            self._store.pop(key, None)
            return None
        return value

    def _set(self, key: str, value: object, ttl: int = _TTL) -> None:
        self._store[key] = (_now_ts() + ttl, value)

    def _delete(self, key: str) -> None:
        self._store.pop(key, None)

    def _touch(self, key: str, ttl: int = _TTL) -> None:
        entry = self._store.get(key)
        if entry is not None:
            self._store[key] = (_now_ts() + ttl, entry[1])

    # -- key helpers -----------------------------------------------------

    @staticmethod
    def _meta_key(scope: str) -> str:
        return f"batch:session:{scope}:meta"

    @staticmethod
    def _subtask_key(scope: str, repo: str) -> str:
        return f"batch:session:{scope}:subtask:{repo}"

    @staticmethod
    def _raw_key(scope: str, repo: str, file: str) -> str:
        return f"batch:session:{scope}:raw:{repo}:{file}"

    @staticmethod
    def _cli_key(scope: str, repo: str) -> str:
        return f"batch:session:{scope}:cli:{repo}"

    def _bg_tasks_key(self, scope: str) -> str:
        return f"batch:session:{scope}:bg_tasks"

    # -- interface -------------------------------------------------------

    async def get_session(self, scope: str) -> Optional[BatchSession]:
        import json as _json
        from sdk.batch.models import BatchSession

        raw = self._get(self._meta_key(scope))
        if raw is None:
            return None
        return BatchSession.model_validate(_json.loads(str(raw)))

    async def set_meta(self, scope: str, session: BatchSession) -> None:
        self._set(
            self._meta_key(scope),
            session.model_dump_json(),
        )

    async def set_subtask(self, scope: str, repo: str, subtask: SubTask) -> None:
        ttl = _TTL_PR if subtask.pr is not None else _TTL
        self._set(self._subtask_key(scope, repo), subtask.model_dump_json(), ttl=ttl)

    async def get_subtask(self, scope: str, repo: str) -> Optional[SubTask]:
        from sdk.batch.models import SubTask

        raw = self._get(self._subtask_key(scope, repo))
        if raw is None:
            return None
        return SubTask.model_validate_json(str(raw))

    async def delete_subtask(self, scope: str, repo: str) -> None:
        from sdk.batch.models import BatchSession

        self._delete(self._subtask_key(scope, repo))
        meta = self._get(self._meta_key(scope))
        if meta is not None:
            import json as _json

            session = BatchSession.model_validate(_json.loads(str(meta)))
            if repo in session.sub_tasks:
                del session.sub_tasks[repo]
                self._set(self._meta_key(scope), session.model_dump_json())

    async def set_raw_diff(
        self, scope: str, repo: str, file: str, diff: str
    ) -> None:
        self._set(self._raw_key(scope, repo, file), diff)

    async def set_raw_diff_many(
        self, scope: str, repo: str, diffs: dict[str, str]
    ) -> None:
        for file, diff in diffs.items():
            self._set(self._raw_key(scope, repo, file), diff)

    async def get_raw_diff(
        self, scope: str, repo: str, file: str
    ) -> Optional[str]:
        val = self._get(self._raw_key(scope, repo, file))
        return str(val) if val is not None else None

    async def set_cli_session(
        self, scope: str, repo: str, session_id: str, iteration: int
    ) -> None:
        payload = json.dumps(
            {
                "session_id": session_id,
                "iteration": iteration,
                "last_at": datetime.utcnow().isoformat(),
            }
        )
        self._set(self._cli_key(scope, repo), payload)

    async def get_cli_session(self, scope: str, repo: str) -> Optional[dict]:
        raw = self._get(self._cli_key(scope, repo))
        if raw is None:
            return None
        return json.loads(str(raw))

    async def register_bg_task(self, scope: str, name: str) -> None:
        key = self._bg_tasks_key(scope)
        if key not in self._bg_tasks:
            self._bg_tasks[key] = set()
        self._bg_tasks[key].add(name)

    async def unregister_bg_task(self, scope: str, name: str) -> None:
        key = self._bg_tasks_key(scope)
        if key in self._bg_tasks:
            self._bg_tasks[key].discard(name)

    async def get_bg_tasks(self, scope: str) -> list[str]:
        key = self._bg_tasks_key(scope)
        return list(self._bg_tasks.get(key, set()))

    async def wipe(self, scope: str) -> None:
        prefix = f"batch:session:{scope}:"
        keys = [k for k in list(self._store) if k.startswith(prefix)]
        for k in keys:
            self._store.pop(k, None)
        self._bg_tasks.pop(self._bg_tasks_key(scope), None)

    async def ping(self) -> bool:
        return True
