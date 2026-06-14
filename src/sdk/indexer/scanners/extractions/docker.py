"""Docker / Compose / Swarm extractions.

Produces three extraction types:

  - ``docker_image`` — every base image referenced by ``FROM`` in any
    Dockerfile, plus every ``image:`` reference in compose services.
  - ``compose_service`` — one row per compose-service definition.
  - ``swarm_stack`` — one row per compose file that uses ``deploy:`` keys
    (the conventional swarm-mode signal).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

from ...db.extractions import RepositoryExtraction
from .._walker import walk_repo
from ._yaml import safe_load_one

logger = logging.getLogger(__name__)

DOCKERFILE_NAME = re.compile(r"^Dockerfile.*$|^.*\.dockerfile$")
COMPOSE_NAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

FROM_LINE = re.compile(
    r"""^\s*FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+)(?:\s+AS\s+\S+)?\s*$""",
    re.IGNORECASE,
)


def scan_docker(
    repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    rows: List[RepositoryExtraction] = []

    for rel, _ in walk_repo(repo_dir):
        name = rel.rsplit("/", 1)[-1]
        full = Path(repo_dir) / rel

        if DOCKERFILE_NAME.match(name):
            rows.extend(
                _from_dockerfile(full, rel, user_id, repository_name)
            )
        elif name in COMPOSE_NAMES:
            rows.extend(
                _from_compose(full, rel, user_id, repository_name)
            )

    return rows


def _from_dockerfile(
    path: Path, rel: str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    rows: List[RepositoryExtraction] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = FROM_LINE.match(line)
                if not m:
                    continue
                ref = m.group("ref")
                if ref == "scratch":
                    continue
                # Skip stage references (case-insensitive) — heuristic: no
                # slash and no colon and not a registered image, treat as
                # stage. Cheap version: only reject single-word lowercase.
                if (
                    "/" not in ref
                    and ":" not in ref
                    and ref.islower()
                    and not _is_likely_image(ref)
                ):
                    continue
                image_name, tag = _split_ref(ref)
                rows.append(
                    RepositoryExtraction(
                        user_id=user_id,
                        repository_name=repository_name,
                        extraction_type="docker_image",
                        data={
                            "image_name": image_name,
                            "tag": tag,
                            "ref": ref,
                            "source": "dockerfile",
                        },
                        evidence=[{"kind": "dockerfile", "path": rel}],
                    )
                )
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
    return rows


def _from_compose(
    path: Path, rel: str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    data = safe_load_one(path)
    if not isinstance(data, dict):
        return []

    rows: List[RepositoryExtraction] = []
    services = data.get("services") or {}
    swarm_signal = False

    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        image = svc.get("image")
        rows.append(
            RepositoryExtraction(
                user_id=user_id,
                repository_name=repository_name,
                extraction_type="compose_service",
                data={
                    "service_name": svc_name,
                    "image": image,
                    "depends_on": _to_list(svc.get("depends_on")),
                    "ports": _to_list(svc.get("ports")),
                    "has_build": "build" in svc,
                },
                evidence=[{"kind": "manifest", "path": rel}],
            )
        )
        if image:
            image_name, tag = _split_ref(image)
            rows.append(
                RepositoryExtraction(
                    user_id=user_id,
                    repository_name=repository_name,
                    extraction_type="docker_image",
                    data={
                        "image_name": image_name,
                        "tag": tag,
                        "ref": image,
                        "source": "compose",
                        "service_name": svc_name,
                    },
                    evidence=[{"kind": "manifest", "path": rel}],
                )
            )
        if isinstance(svc.get("deploy"), dict):
            swarm_signal = True

    if swarm_signal:
        rows.append(
            RepositoryExtraction(
                user_id=user_id,
                repository_name=repository_name,
                extraction_type="swarm_stack",
                data={
                    "compose_file": rel,
                    "service_count": len(services),
                },
                evidence=[{"kind": "manifest", "path": rel}],
            )
        )

    return rows


def _split_ref(ref: str) -> Tuple[str, Optional[str]]:
    """Split ``image:tag`` or ``host/image:tag`` into ``(image, tag)``.

    Digests (``image@sha256:...``) preserve the digest as the "tag" value.
    """
    if "@" in ref:
        name, _, digest = ref.partition("@")
        return name, digest
    if ":" in ref:
        # If there's a port in the host (host:port/image), the rightmost
        # colon belongs to the tag only when it's after the last slash.
        last_slash = ref.rfind("/")
        last_colon = ref.rfind(":")
        if last_colon > last_slash:
            return ref[:last_colon], ref[last_colon + 1 :]
    return ref, None


def _to_list(v) -> List:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.keys())
    return [v]


def _is_likely_image(ref: str) -> bool:
    """Conservative heuristic: anything containing a registry-like dot or
    a digit looks more like an image than a stage alias."""
    return "." in ref or any(c.isdigit() for c in ref)


__all__ = ["scan_docker"]
