"""In-memory TTL cache for GitHub API responses."""

import time
from dataclasses import dataclass, field


@dataclass
class _CacheEntry:
    value: object
    expires_at: float


@dataclass
class TTLCache:
    """Simple in-memory cache with per-entry TTL expiration."""

    default_ttl: float = 300.0  # 5 minutes
    _store: dict[str, _CacheEntry] = field(default_factory=dict)

    def get(self, key: str) -> object | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: object, ttl: float | None = None):
        expires_at = time.monotonic() + (ttl if ttl is not None else self.default_ttl)
        self._store[key] = _CacheEntry(value=value, expires_at=expires_at)

    def invalidate(self, key: str):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()


# Shared cache instances
tree_cache = TTLCache(default_ttl=300.0)
file_cache = TTLCache(default_ttl=120.0)
