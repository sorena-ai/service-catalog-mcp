"""Language scanner — count file extensions, emit weighted languages."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List

from sdk.indexer.db.languages import RepositoryLanguage
from sdk.indexer.lang_extensions import EXT_LANGUAGE

MIN_FILES = 1
TOP_N = 10


def scan_languages(
    files: list[tuple[str, int]], user_id: str, repository_name: str
) -> List[RepositoryLanguage]:
    counts: Counter = Counter()
    for rel, _ in files:
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
