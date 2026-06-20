"""YAML loading helpers shared by extraction scanners.

PyYAML's full loader is unsafe; everywhere we use ``safe_load`` /
``safe_load_all``. Helpers tolerate missing PyYAML so the scanner package
remains importable in environments where it isn't installed (callers can
gracefully no-op).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator, List

logger = logging.getLogger(__name__)


def safe_load_one(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML missing; skipping %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as exc:
        logger.warning("Failed to parse YAML %s: %s", path, exc)
        return None


def safe_load_all(path: Path) -> List[Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML missing; skipping %s", path)
        return []
    docs: List[Any] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for d in yaml.safe_load_all(f):
                if d is not None:
                    docs.append(d)
    except Exception as exc:
        logger.warning("Failed to parse YAML %s: %s", path, exc)
    return docs


