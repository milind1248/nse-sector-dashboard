import time
from functools import wraps
from typing import Any, Callable

_cache: dict[str, tuple[Any, float]] = {}


def timed_cache(ttl_seconds: int = 21600):
    """In-memory TTL cache. Drop-in replacement for functools.lru_cache with expiry."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            now = time.time()
            if key in _cache:
                value, ts = _cache[key]
                if now - ts < ttl_seconds:
                    return value
            result = func(*args, **kwargs)
            _cache[key] = (result, now)
            return result
        wrapper.cache_clear = lambda: _cache.clear()
        return wrapper
    return decorator


def invalidate_all():
    _cache.clear()
