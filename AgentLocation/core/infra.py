from __future__ import annotations
import asyncio, json, logging, random, time
from enum import Enum
from typing import Any, Callable, Optional
import asyncpg
import redis.asyncio as aioredis
from core.config import settings

log = logging.getLogger("dourbia.infra")

class CircuitState(Enum):
    CLOSED="closed"; OPEN="open"; HALF_OPEN="half_open"

class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, recovery_timeout=60.0, window_size=10):
        self.name=name; self.failure_threshold=failure_threshold
        self.recovery_timeout=recovery_timeout; self.window_size=window_size
        self.state=CircuitState.CLOSED; self._window=[]; self.last_failure_time=0.0
        self._lock=asyncio.Lock(); self.total_calls=0; self.total_failures=0; self.total_rejected=0

    def _failure_rate(self):
        return self._window.count(False)/len(self._window) if self._window else 0.0

    async def call(self, coro):
        async with self._lock:
            self.total_calls += 1
            if self.state == CircuitState.OPEN:
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.recovery_timeout: self.state = CircuitState.HALF_OPEN
                else:
                    self.total_rejected += 1
                    raise RuntimeError(f"Circuit {self.name} OPEN — retry dans {self.recovery_timeout-elapsed:.0f}s")
        try:
            result = await coro
            async with self._lock:
                self._window.append(True)
                if len(self._window) > self.window_size: self._window.pop(0)
                if self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.CLOSED; self._window.clear()
            return result
        except Exception as e:
            async with self._lock:
                self._window.append(False)
                if len(self._window) > self.window_size: self._window.pop(0)
                self.last_failure_time = time.time(); self.total_failures += 1
                if self._failure_rate() >= self.failure_threshold/self.window_size or self.state == CircuitState.HALF_OPEN:
                    self.state = CircuitState.OPEN
            raise

    def get_metrics(self):
        return {"name":self.name,"state":self.state.value,"failure_rate":round(self._failure_rate(),3),
                "total_calls":self.total_calls,"total_failures":self.total_failures,"total_rejected":self.total_rejected}

cb_groq     = CircuitBreaker("groq",     failure_threshold=5, recovery_timeout=60)
cb_scraping = CircuitBreaker("scraping", failure_threshold=5, recovery_timeout=60)
cb_guard    = CircuitBreaker("guard",    failure_threshold=3, recovery_timeout=30)

async def with_retry(coro_fn, max_retries=3, base_delay=1.0, max_delay=30.0, retryable_exceptions=(Exception,)):
    for attempt in range(max_retries+1):
        try: return await coro_fn()
        except retryable_exceptions as e:
            if attempt == max_retries: raise
            delay = min(base_delay*(2**attempt)+random.uniform(0,1), max_delay)
            log.warning(f"[RETRY] {attempt+1}/{max_retries} — {e} — retry {delay:.1f}s")
            await asyncio.sleep(delay)

_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()

async def get_pool() -> asyncpg.Pool:
    """
    FIX RACE CONDITION : le Lock garantit qu'un seul worker crée le pool,
    même sous charge concurrente (plusieurs requêtes au démarrage).
    Sans Lock, deux workers pouvaient créer deux pools et le second
    écrasait le premier sans le fermer → fuite de connexions DB.
    """
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:  # Double-check après acquisition du lock
            _pool = await asyncpg.create_pool(
                settings.database_url, min_size=5, max_size=20,
                command_timeout=30,timeout =5, server_settings={"jit": "off"})
            log.info("[DB] Pool créé")
    return _pool

async def close_pool():
    global _pool
    if _pool: await _pool.close(); _pool = None

_redis = None
async def get_redis():
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        log.info("[REDIS] Connecté")
    return _redis

async def close_redis():
    global _redis
    if _redis: await _redis.aclose(); _redis = None

def record_to_dict(record) -> dict:
    if record is None: return {}
    from datetime import date as _d
    from decimal import Decimal
    d = dict(record)
    for k,v in d.items():
        if isinstance(v,_d): d[k] = v.isoformat()
        elif isinstance(v, Decimal): d[k] = float(v)
    return d

_NULL_STRINGS = frozenset({"null","none","undefined","","inconnu","n/a","na"})
