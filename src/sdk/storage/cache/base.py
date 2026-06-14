"""Cache ABC for batch session state.

All methods accept *user_id* as the namespace key — an opaque string the
caller controls. The cache has no opinion on its value.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sdk.batch.models import BatchSession, SubTask


class Cache(ABC):
    @abstractmethod
    async def get_session(self, scope: str) -> Optional[BatchSession]:
        ...

    @abstractmethod
    async def set_meta(self, scope: str, session: BatchSession) -> None:
        ...

    @abstractmethod
    async def set_subtask(self, scope: str, repo: str, subtask: SubTask) -> None:
        ...

    @abstractmethod
    async def get_subtask(self, scope: str, repo: str) -> Optional[SubTask]:
        ...

    @abstractmethod
    async def delete_subtask(self, scope: str, repo: str) -> None:
        ...

    @abstractmethod
    async def set_raw_diff(self, scope: str, repo: str, file: str, diff: str) -> None:
        ...

    @abstractmethod
    async def set_raw_diff_many(self, scope: str, repo: str, diffs: dict[str, str]) -> None:
        ...

    @abstractmethod
    async def get_raw_diff(self, scope: str, repo: str, file: str) -> Optional[str]:
        ...

    @abstractmethod
    async def set_cli_session(self, scope: str, repo: str, session_id: str, iteration: int) -> None:
        ...

    @abstractmethod
    async def get_cli_session(self, scope: str, repo: str) -> Optional[dict]:
        ...

    @abstractmethod
    async def register_bg_task(self, scope: str, name: str) -> None:
        ...

    @abstractmethod
    async def unregister_bg_task(self, scope: str, name: str) -> None:
        ...

    @abstractmethod
    async def get_bg_tasks(self, scope: str) -> list[str]:
        ...

    @abstractmethod
    async def wipe(self, scope: str) -> None:
        ...

    @abstractmethod
    async def ping(self) -> bool:
        ...
