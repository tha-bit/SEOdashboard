"""
In-memory cache for expensive calculations across large datasets.
Provides fast lookups with explicit invalidation and memory reclamation on mutations.
"""

from __future__ import annotations

import gc
from typing import Any

# Global project-level caches
_ARCHITECTURE_ISSUES_CACHE: dict[str, list[dict[str, Any]]] = {}
_INTERNAL_LINK_FINDINGS_CACHE: dict[str, list[dict[str, Any]]] = {}
_ON_PAGE_ISSUES_CACHE: dict[str, list[dict[str, Any]]] = {}
_LATEST_METADATA_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_SNAPSHOT_COUNTS_CACHE: dict[str, dict[str, dict[str, int]]] = {}

# Maximum number of active projects cached in memory simultaneously to prevent memory bloat
MAX_CACHED_PROJECTS = 2


def _prune_cache_if_needed(cache_dict: dict[str, Any]) -> None:
    if len(cache_dict) > MAX_CACHED_PROJECTS:
        # Evict oldest entry (FIFO)
        oldest_key = next(iter(cache_dict))
        cache_dict.pop(oldest_key, None)


def get_cached_architecture_issues(project_id: str) -> list[dict[str, Any]] | None:
    return _ARCHITECTURE_ISSUES_CACHE.get(project_id)


def set_cached_architecture_issues(project_id: str, issues: list[dict[str, Any]]) -> None:
    _prune_cache_if_needed(_ARCHITECTURE_ISSUES_CACHE)
    _ARCHITECTURE_ISSUES_CACHE[project_id] = issues


def get_cached_internal_link_findings(project_id: str) -> list[dict[str, Any]] | None:
    return _INTERNAL_LINK_FINDINGS_CACHE.get(project_id)


def set_cached_internal_link_findings(project_id: str, findings: list[dict[str, Any]]) -> None:
    _prune_cache_if_needed(_INTERNAL_LINK_FINDINGS_CACHE)
    _INTERNAL_LINK_FINDINGS_CACHE[project_id] = findings


def get_cached_on_page_issues(project_id: str) -> list[dict[str, Any]] | None:
    return _ON_PAGE_ISSUES_CACHE.get(project_id)


def set_cached_on_page_issues(project_id: str, issues: list[dict[str, Any]]) -> None:
    _prune_cache_if_needed(_ON_PAGE_ISSUES_CACHE)
    _ON_PAGE_ISSUES_CACHE[project_id] = issues


def get_cached_latest_metadata(project_id: str) -> dict[str, dict[str, Any]] | None:
    return _LATEST_METADATA_CACHE.get(project_id)


def set_cached_latest_metadata(project_id: str, metadata: dict[str, dict[str, Any]]) -> None:
    _prune_cache_if_needed(_LATEST_METADATA_CACHE)
    _LATEST_METADATA_CACHE[project_id] = metadata


def get_cached_snapshot_counts(snapshot_id: str) -> dict[str, dict[str, int]] | None:
    return _SNAPSHOT_COUNTS_CACHE.get(snapshot_id)


def set_cached_snapshot_counts(snapshot_id: str, counts: dict[str, dict[str, int]]) -> None:
    _prune_cache_if_needed(_SNAPSHOT_COUNTS_CACHE)
    _SNAPSHOT_COUNTS_CACHE[snapshot_id] = counts


def invalidate_project_cache(project_id: str | None = None) -> None:
    """Invalidate cached metrics and issues for a project or all projects, and reclaim memory."""
    if project_id:
        _ARCHITECTURE_ISSUES_CACHE.pop(project_id, None)
        _INTERNAL_LINK_FINDINGS_CACHE.pop(project_id, None)
        _ON_PAGE_ISSUES_CACHE.pop(project_id, None)
        _LATEST_METADATA_CACHE.pop(project_id, None)
        _SNAPSHOT_COUNTS_CACHE.clear()
    else:
        _ARCHITECTURE_ISSUES_CACHE.clear()
        _INTERNAL_LINK_FINDINGS_CACHE.clear()
        _ON_PAGE_ISSUES_CACHE.clear()
        _LATEST_METADATA_CACHE.clear()
        _SNAPSHOT_COUNTS_CACHE.clear()
    gc.collect()


def clear_all_caches() -> None:
    """Explicitly release all cached data structures and run garbage collection."""
    invalidate_project_cache(None)
