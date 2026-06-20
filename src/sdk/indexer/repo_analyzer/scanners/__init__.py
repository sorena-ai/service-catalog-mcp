"""Detail scanners — curated files and dependencies.

Extraction scanners (docker, helm, k8s, …) live under ``extractions/``.
Each scanner returns DB row objects; the coordinator owns persistence.
"""

from .dependencies import scan_dependencies
from .files import scan_files

__all__ = [
    "scan_dependencies",
    "scan_files",
]
