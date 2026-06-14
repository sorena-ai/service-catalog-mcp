"""Result models for IndexSearchService — the single source of truth for search output shapes."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class EvidenceItem(BaseModel):
    kind: str
    path: Optional[str] = None


class RepositoryMatch(BaseModel):
    repository_name: str
    evidence: List[EvidenceItem] = []


class ContextHit(BaseModel):
    repository_name: str
    context_type: str
    snippet: str
    tags: List[str] = []
    workspace_path: Optional[str] = None


class SearchResult(BaseModel):
    exact_matches: List[RepositoryMatch] = []
    near_matches: List[RepositoryMatch] = []
    not_found: List[str] = []


class SearchResultNL(BaseModel):
    exact_matches: List[RepositoryMatch] = []
    near_matches: List[RepositoryMatch] = []
    not_found: List[str] = []
    context_hits: List[ContextHit] = []
    resolved_filters: dict = {}
    resolver_keywords: List[str] = []


class CodebaseGlossary(BaseModel):
    terminology: str = ""
    query_hints: str = ""
    has_glossary: bool = False
