"""Extraction scanners — write into the generic ``repository_extractions``
collection. Each scanner returns a list of ``RepositoryExtraction`` rows;
the orchestrator persists them.
"""

from .chef import scan_chef
from .docker import scan_docker
from .frameworks import scan_frameworks
from .github_actions import scan_github_actions
from .helm import scan_helm
from .kubernetes import scan_kubernetes
from .platforms import scan_platforms, scan_platforms_from_tree
from .terraform import scan_terraform

__all__ = [
    "scan_chef",
    "scan_docker",
    "scan_frameworks",
    "scan_github_actions",
    "scan_helm",
    "scan_kubernetes",
    "scan_platforms",
    "scan_platforms_from_tree",
    "scan_terraform",
]
