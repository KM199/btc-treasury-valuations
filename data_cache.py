"""Unified network fetch cache with TTL for data pull scripts."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

_cache_lock = threading.Lock()  # guards _key_locks dict mutation only
_key_locks: dict[str, threading.Lock] = {}
_run_hits: set[str] = set()
_run_fresh: set[str] = set()
_hits_lock = threading.Lock()


def begin_cache_tracking() -> None:
    """Clear per-run cache-hit registry (call at start of fetch_data.py)."""
    with _hits_lock:
        _run_hits.clear()
        _run_fresh.clear()


def run_cache_hits() -> frozenset[str]:
    """Cache keys that were served from cache during the current tracked run."""
    with _hits_lock:
        return frozenset(_run_hits)


def run_fresh_fetches() -> frozenset[str]:
    """Cache keys that were re-fetched from the network during the current tracked run."""
    with _hits_lock:
        return frozenset(_run_fresh)


def record_cache_hit(key: str) -> None:
    """Mark a key as unchanged for this run (e.g. reused on-disk fallback)."""
    with _hits_lock:
        _run_hits.add(key)


def _record_cache_hit(key: str) -> None:
    record_cache_hit(key)


def _record_fresh_fetch(key: str) -> None:
    with _hits_lock:
        _run_fresh.add(key)

import requests

from strc_paths import CACHE_DIR, ensure_output_dirs

DEFAULT_CACHE_TTL_SECONDS = 3600

_BYTES_MARKER = "__cache_bytes__"


def cache_path(key: str) -> Path:
    """Return a safe filesystem path for a cache key."""
    safe = re.sub(r"[^\w\-]", "_", key)
    if len(safe) > 200:
        safe = hashlib.sha256(key.encode()).hexdigest()[:32]
    return CACHE_DIR / f"{safe}.json"


def _meta_path(key: str) -> Path:
    return cache_path(key).with_suffix(".meta.json")


def is_fresh(key: str, ttl: int = DEFAULT_CACHE_TTL_SECONDS) -> bool:
    """Return True if cached data exists and is within TTL."""
    meta_path = _meta_path(key)
    data_path = cache_path(key)
    if not meta_path.is_file() or not data_path.is_file():
        return False
    try:
        with meta_path.open() as f:
            meta = json.load(f)
        fetched_at = float(meta.get("fetched_at", 0))
        return (time.time() - fetched_at) < ttl
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def read_cache(key: str) -> Any | None:
    """Read cached data for key, or None if missing/unreadable."""
    data_path = cache_path(key)
    if not data_path.is_file():
        return None
    try:
        with data_path.open() as f:
            payload = json.load(f)
        if isinstance(payload, dict) and _BYTES_MARKER in payload:
            return base64.b64decode(payload[_BYTES_MARKER])
        return payload
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def write_cache(key: str, data: Any) -> None:
    """Serialize and persist data with a sidecar metadata file.

    Writes go to a temp file and then an atomic rename, so a concurrent reader
    (possibly in another process) never observes a partially-written file.
    """
    ensure_output_dirs()
    data_path = cache_path(key)
    meta_path = _meta_path(key)

    if isinstance(data, bytes):
        payload: Any = {_BYTES_MARKER: base64.b64encode(data).decode("ascii")}
    else:
        payload = data

    tmp_data = data_path.with_suffix(data_path.suffix + ".tmp")
    with tmp_data.open("w") as f:
        json.dump(payload, f)
    tmp_data.replace(data_path)

    tmp_meta = meta_path.with_suffix(meta_path.suffix + ".tmp")
    with tmp_meta.open("w") as f:
        json.dump({"key": key, "fetched_at": time.time()}, f)
    tmp_meta.replace(meta_path)


def _lock_for_key(key: str) -> threading.Lock:
    """Return a lock private to this cache key, creating it on first use."""
    with _cache_lock:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def get_or_fetch(
    key: str,
    fetch_fn: Callable[[], Any],
    ttl: int = DEFAULT_CACHE_TTL_SECONDS,
    force_refresh: bool = False,
) -> Any:
    """Return cached data when fresh; otherwise call fetch_fn and cache result.

    The whole check-then-fetch-then-write sequence is serialized per cache key,
    so concurrent callers requesting the same key (e.g. two ThreadPoolExecutor
    tasks that happen to share a key) don't both miss and both hit the network —
    only the first pays the fetch cost; the rest block and then see its result.
    """
    with _lock_for_key(key):
        if not force_refresh and is_fresh(key, ttl):
            cached = read_cache(key)
            if cached is not None:
                print(f"  ✓ Cache hit: {key}")
                _record_cache_hit(key)
                return cached

        data = fetch_fn()
        _record_fresh_fetch(key)
        write_cache(key, data)
        return data


def cached_http_get(
    url: str,
    headers: dict | None = None,
    timeout: float = 15,
    cache_key: str | None = None,
    ttl: int = DEFAULT_CACHE_TTL_SECONDS,
    force: bool = False,
) -> str:
    """Fetch URL text with caching (for strategy.com HTML pages)."""

    key = cache_key or url

    def fetch() -> str:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text

    return get_or_fetch(key, fetch, ttl=ttl, force_refresh=force)
