"""Language scanner — count file extensions, emit weighted languages."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List

from ..db.languages import RepositoryLanguage
from ._walker import walk_repo

EXT_LANGUAGE = {
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".cs": "csharp",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
}

MIN_FILES = 1
TOP_N = 10


def scan_languages(
    repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryLanguage]:
    counts: Counter = Counter()
    for rel, _ in walk_repo(repo_dir):
        ext = _ext(rel)
        lang = EXT_LANGUAGE.get(ext)
        if lang:
            counts[lang] += 1

    total = sum(counts.values())
    if total == 0:
        return []

    rows: List[RepositoryLanguage] = []
    for lang, n in counts.most_common(TOP_N):
        if n < MIN_FILES:
            continue
        rows.append(
            RepositoryLanguage(
                user_id=user_id,
                repository_name=repository_name,
                language=lang,
                confidence=round(n / total, 4),
                evidence=[{"kind": "source", "path": "", "snippet": f"{n} files"}],
            )
        )
    return rows


def _ext(rel_path: str) -> str:
    idx = rel_path.rfind(".")
    if idx == -1:
        return ""
    return rel_path[idx:].lower()
