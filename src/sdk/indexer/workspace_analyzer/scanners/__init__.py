"""Structural scanners — describe overall repo shape (tree, languages, workspaces).

Each scanner takes the walked file list and returns DB row objects; the
coordinator owns persistence and ordering.
"""

from .languages import scan_languages
from .tree import scan_tree
from .workspaces import scan_workspaces

__all__ = [
    "scan_languages",
    "scan_tree",
    "scan_workspaces",
]
