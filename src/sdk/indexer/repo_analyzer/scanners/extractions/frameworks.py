"""Framework extractions derived from parsed dependencies.

A small lookup table maps known dependency names to a framework + the
language they typically run with. We never invent: every match must
correspond to an actual ``RepositoryDependency`` row produced by the
deterministic dependency scanner.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

from sdk.indexer.db.dependencies import RepositoryDependency
from sdk.indexer.db.extractions import RepositoryExtraction

# (matcher_function, framework, language)
DepName = str

_FRAMEWORK_MAP: dict[Tuple[str, DepName], Tuple[str, str]] = {
    # PM-qualified entries take priority because the same name (e.g. "react")
    # never appears across PMs in practice, but this keeps things explicit.
    ("npm", "react"): ("react", "javascript"),
    ("npm", "next"): ("nextjs", "javascript"),
    ("npm", "vue"): ("vue", "javascript"),
    ("npm", "express"): ("express", "javascript"),
    ("npm", "@nestjs/core"): ("nestjs", "javascript"),
    ("npm", "fastify"): ("fastify", "javascript"),
    ("pip", "fastapi"): ("fastapi", "python"),
    ("pip", "django"): ("django", "python"),
    ("pip", "flask"): ("flask", "python"),
    ("poetry", "fastapi"): ("fastapi", "python"),
    ("poetry", "django"): ("django", "python"),
    ("poetry", "flask"): ("flask", "python"),
    ("uv", "fastapi"): ("fastapi", "python"),
    ("uv", "django"): ("django", "python"),
    ("uv", "flask"): ("flask", "python"),
    ("go_modules", "github.com/gin-gonic/gin"): ("gin", "go"),
    ("go_modules", "github.com/labstack/echo"): ("echo", "go"),
    ("go_modules", "github.com/go-chi/chi"): ("chi", "go"),
    ("go_modules", "github.com/gofiber/fiber"): ("fiber", "go"),
    ("bundler", "rails"): ("rails", "ruby"),
    ("composer", "laravel/framework"): ("laravel", "php"),
}


def scan_frameworks(
    deps: Iterable[RepositoryDependency], user_id: str, repository_name: str
) -> List[RepositoryExtraction]:
    rows: List[RepositoryExtraction] = []
    seen: set[Tuple[str, str]] = set()
    for dep in deps:
        key = (dep.package_manager, dep.name_normalized)
        # Try exact match first; for go_modules also try prefix match
        # (gin imports may include version suffix paths).
        match = _FRAMEWORK_MAP.get(key)
        if not match and dep.package_manager == "go_modules":
            for (pm, prefix), value in _FRAMEWORK_MAP.items():
                if pm == "go_modules" and dep.name_normalized.startswith(prefix):
                    match = value
                    break
        if not match:
            continue
        framework, language = match
        if (framework, language) in seen:
            continue
        seen.add((framework, language))
        rows.append(
            RepositoryExtraction(
                user_id=user_id,
                repository_name=repository_name,
                extraction_type="framework",
                data={
                    "framework": framework,
                    "language": language,
                    "source_dependency": dep.name,
                    "package_manager": dep.package_manager,
                },
                evidence=dep.evidence,
            )
        )
    return rows


__all__ = ["scan_frameworks"]
