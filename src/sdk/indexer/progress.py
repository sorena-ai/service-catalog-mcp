"""Short-lived in-memory indexing progress snapshots.

This is intentionally process-local and disposable. It exists only to power the
GitHub install callback page until the dashboard owns this experience.
"""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable, Optional


_PROGRESS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _repo(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pending",
        "step": None,
        "error_message": None,
    }


def _touch(entry: dict[str, Any]) -> None:
    entry["updated_at"] = _now()


def _repo_map(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {repo["name"]: repo for repo in entry.get("repos", [])}


def ensure_event_for_user(user_id: str, repository_names: Iterable[str]) -> None:
    names = [name for name in repository_names if name]
    if not names:
        return

    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            now = _now()
            _PROGRESS[user_id] = {
                "user_id": user_id,
                "event_id": None,
                "phase": "waiting_for_repos",
                "started_at": now,
                "updated_at": now,
                "current_repo": None,
                "current_step": None,
                "error_message": None,
                "repos": [_repo(name) for name in sorted(set(names))],
            }
            return

        if entry.get("phase") in {"done", "failed"}:
            now = _now()
            _PROGRESS[user_id] = {
                "user_id": user_id,
                "event_id": None,
                "phase": "waiting_for_repos",
                "started_at": now,
                "updated_at": now,
                "current_repo": None,
                "current_step": None,
                "error_message": None,
                "repos": [_repo(name) for name in sorted(set(names))],
            }
            return

        if entry.get("phase") != "waiting_for_repos":
            return

        repos = _repo_map(entry)
        for name in names:
            repos.setdefault(name, _repo(name))
        entry["repos"] = [repos[name] for name in sorted(repos)]
        _touch(entry)


def begin_event(user_id: str, event_id: str, repository_names: Iterable[str]) -> None:
    now = _now()
    with _LOCK:
        _PROGRESS[user_id] = {
            "user_id": user_id,
            "event_id": event_id,
            "phase": "cloning",
            "started_at": now,
            "updated_at": now,
            "current_repo": None,
            "current_step": None,
            "error_message": None,
            "repos": [_repo(name) for name in sorted(set(repository_names))],
        }


def set_phase(user_id: str, phase: str) -> None:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            return
        entry["phase"] = phase
        entry["current_repo"] = None
        entry["current_step"] = None
        _touch(entry)


def set_repo_step(user_id: str, repo_name: str, step: str) -> None:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            return
        repos = _repo_map(entry)
        repo = repos.setdefault(repo_name, _repo(repo_name))
        repo["status"] = "in_progress"
        repo["step"] = step
        repo["error_message"] = None
        entry["repos"] = [repos[name] for name in sorted(repos)]
        entry["current_repo"] = repo_name
        entry["current_step"] = step
        _touch(entry)


def mark_repo_done(user_id: str, repo_name: str) -> None:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            return
        repos = _repo_map(entry)
        repo = repos.setdefault(repo_name, _repo(repo_name))
        repo["status"] = "done"
        repo["step"] = None
        repo["error_message"] = None
        entry["repos"] = [repos[name] for name in sorted(repos)]
        if entry.get("current_repo") == repo_name:
            entry["current_repo"] = None
            entry["current_step"] = None
        _touch(entry)


def mark_repo_failed(user_id: str, repo_name: str, error_message: str) -> None:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            return
        repos = _repo_map(entry)
        repo = repos.setdefault(repo_name, _repo(repo_name))
        repo["status"] = "failed"
        repo["step"] = None
        repo["error_message"] = error_message
        entry["repos"] = [repos[name] for name in sorted(repos)]
        if entry.get("current_repo") == repo_name:
            entry["current_repo"] = None
            entry["current_step"] = None
        _touch(entry)


def complete_event(user_id: str) -> None:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            return
        entry["phase"] = "done"
        entry["current_repo"] = None
        entry["current_step"] = None
        for repo in entry.get("repos", []):
            if repo.get("status") != "failed":
                repo["status"] = "done"
                repo["step"] = None
                repo["error_message"] = None
        _touch(entry)


def fail_event(user_id: str, error_message: str) -> None:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        if entry is None:
            return
        entry["phase"] = "failed"
        entry["current_repo"] = None
        entry["current_step"] = None
        entry["error_message"] = error_message
        for repo in entry.get("repos", []):
            repo["status"] = "failed"
            repo["step"] = None
            repo["error_message"] = error_message
        _touch(entry)


def snapshot(user_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        entry = _PROGRESS.get(user_id)
        return deepcopy(entry) if entry is not None else None

