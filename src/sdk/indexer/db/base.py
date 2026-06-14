"""Shared types for indexer DB documents.

Evidence rows are plain dicts with the documented shape:

    {
        "kind": str,          # one of vocab.EVIDENCE_KINDS
        "path": str,          # repo-relative file path
        "line": int | None,   # optional 1-based line number
        "snippet": str | None # optional short snippet
    }

`evidence` fields throughout the indexer DB are typed as `list[Evidence]`.
"""

from typing import Any, Dict, List

Evidence = Dict[str, Any]
EvidenceList = List[Evidence]
