"""GitHub Actions extractions.

Produces two extraction types from ``.github/workflows/*.yml``:

  - ``github_action`` — one row per ``uses:`` reference, parsed into
    ``action_owner`` / ``action_name`` / ``version_ref``.
  - ``ci_workflow`` — one row per workflow file with the high-level shape
    (name, triggers, job count, runner labels).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from sdk.indexer.db.extractions import RepositoryExtraction
from ._yaml import safe_load_one

WORKFLOW_DIR = ".github/workflows"

# ``uses: actions/checkout@v4``  /  ``uses: ./local/action`` /
# ``uses: docker://image:tag``
USES_REF = re.compile(
    r"^(?P<path>[^@]+)(?:@(?P<ref>.+))?$"
)


def scan_github_actions(
    files: list[tuple[str, int]], repo_dir: Path | str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    base = Path(repo_dir)
    rows: List[RepositoryExtraction] = []
    
    for rel, _ in files:
        if rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml")):
            path = base / rel
            rows.extend(_from_workflow(path, rel, user_id, repository_name))
            
    return rows


def _from_workflow(
    path: Path, rel: str, user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    data = safe_load_one(path)
    if not isinstance(data, dict):
        return []

    rows: List[RepositoryExtraction] = []
    triggers = _normalize_triggers(data.get("on") or data.get(True))
    jobs = data.get("jobs") or {}
    runner_labels = _collect_runners(jobs)

    rows.append(
        RepositoryExtraction(
            user_id=user_id,
            repository_name=repository_name,
            extraction_type="ci_workflow",
            data={
                "workflow_file": rel,
                "name": data.get("name"),
                "triggers": triggers,
                "job_count": len(jobs) if isinstance(jobs, dict) else 0,
                "job_names": list(jobs.keys()) if isinstance(jobs, dict) else [],
                "runners": sorted(set(runner_labels)),
            },
            evidence=[{"kind": "workflow", "path": rel}],
        )
    )

    # Walk steps for ``uses:``.
    if isinstance(jobs, dict):
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []) or []:
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not uses:
                    continue
                parsed = _parse_uses(uses)
                if not parsed:
                    continue
                owner, name, version = parsed
                rows.append(
                    RepositoryExtraction(
                        user_id=user_id,
                        repository_name=repository_name,
                        extraction_type="github_action",
                        data={
                            "action_owner": owner,
                            "action_name": name,
                            "version_ref": version,
                            "raw": uses,
                            "workflow_file": rel,
                            "job_name": job_name,
                        },
                        evidence=[{"kind": "workflow", "path": rel}],
                    )
                )
    return rows


def _normalize_triggers(on) -> List[str]:
    if on is None:
        return []
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(x) for x in on]
    if isinstance(on, dict):
        return sorted(on.keys())
    return []


def _collect_runners(jobs) -> List[str]:
    out: List[str] = []
    if not isinstance(jobs, dict):
        return out
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        runs_on = job.get("runs-on")
        if isinstance(runs_on, str):
            out.append(runs_on)
        elif isinstance(runs_on, list):
            out.extend(str(x) for x in runs_on)
    return out


def _parse_uses(raw: str) -> Optional[Tuple[Optional[str], str, Optional[str]]]:
    raw = raw.strip()
    if raw.startswith("./") or raw.startswith("../") or raw.startswith("docker://"):
        return None, raw, None
    m = USES_REF.match(raw)
    if not m:
        return None
    path = m.group("path")
    version = m.group("ref")
    parts = path.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1], version
    return None, path, version


__all__ = ["scan_github_actions"]
