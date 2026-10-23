"""Short-lived per-user conversation state (quiz progress, follow-up context).

Features talk to the SessionStore protocol. Production keeps state in Supabase behind an
in-memory cache so it survives a Space restart; tests and local runs use memory only.
"""

from __future__ import annotations

import copy
import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from time import time
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.tools.kpop_radar import SupabaseRestClient

logger = logging.getLogger(__name__)

SESSION_TABLE = "bot_sessions"


class SessionStore(Protocol):
    kind: str

    def get(self, namespace: str, key: str) -> dict[str, Any] | None: ...

    def set(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: float) -> None: ...

    def delete(self, namespace: str, key: str) -> None: ...

    def status(self) -> dict[str, Any]: ...


class InMemorySessionStore:
    """Per-process store. Each namespace keeps at most max_entries, evicting the stalest."""

    kind = "memory"

    def __init__(self, clock: Callable[[], float] = time, max_entries: int = 500) -> None:
        self.clock = clock
        self.max_entries = max_entries
        self._namespaces: dict[str, OrderedDict[str, tuple[float, dict[str, Any]]]] = {}

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        entries = self._namespaces.get(namespace, OrderedDict())
        entry = entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self.clock() > expires_at:
            entries.pop(key, None)
            return None
        return copy.deepcopy(value)

    def set(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: float) -> None:
        entries = self._namespaces.setdefault(namespace, OrderedDict())
        entries[key] = (self.clock() + ttl_seconds, copy.deepcopy(value))
        entries.move_to_end(key)
        while len(entries) > self.max_entries:
            entries.popitem(last=False)

    def delete(self, namespace: str, key: str) -> None:
        self._namespaces.get(namespace, OrderedDict()).pop(key, None)

    def status(self) -> dict[str, Any]:
        return {"kind": self.kind, "ok": True}


class SupabaseSessionStore:
    """Durable store in the bot_sessions table (see supabase/bot_sessions_schema.sql)."""

    kind = "supabase"

    def __init__(self, client: SupabaseRestClient, clock: Callable[[], float] = time) -> None:
        self.client = client
        self.clock = clock

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        rows = self.client.request(
            "GET",
            SESSION_TABLE,
            params={
                "select": "payload",
                "namespace": f"eq.{namespace}",
                "session_key": f"eq.{key}",
                "expires_at": f"gt.{_iso(self.clock())}",
                "limit": "1",
            },
        )
        if not rows:
            return None
        payload = rows[0].get("payload")
        return payload if isinstance(payload, dict) else None

    def set(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: float) -> None:
        now = self.clock()
        self.client.request(
            "POST",
            SESSION_TABLE,
            params={"on_conflict": "namespace,session_key"},
            json_payload={
                "namespace": namespace,
                "session_key": key,
                "payload": value,
                "expires_at": _iso(now + ttl_seconds),
                "updated_at": _iso(now),
            },
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete(self, namespace: str, key: str) -> None:
        self.client.request(
            "DELETE",
            SESSION_TABLE,
            params={"namespace": f"eq.{namespace}", "session_key": f"eq.{key}"},
            prefer="return=minimal",
        )

    def status(self) -> dict[str, Any]:
        """Reports whether bot_sessions is reachable, e.g. before its migration has run."""
        try:
            self.client.request("GET", SESSION_TABLE, params={"select": "namespace", "limit": "1"})
        except Exception as exc:
            return {"kind": self.kind, "ok": False, "error": str(exc)[:300]}
        return {"kind": self.kind, "ok": True}


class CachedSessionStore:
    """Serves reads from memory and writes through to a durable backend.

    Assumes a single bot process, as on the Space: memory is authoritative for everything
    this process wrote, and the backend is only read after a restart. Misses are cached
    too, so free-text messages do not cost a backend round trip each. Backend errors are
    logged and the bot keeps working from memory instead of failing the reply.
    """

    _ABSENT = "__absent__"

    def __init__(
        self,
        backend: SessionStore,
        cache: InMemorySessionStore,
        miss_ttl_seconds: float = 300,
    ) -> None:
        self.backend = backend
        self.cache = cache
        self.miss_ttl_seconds = miss_ttl_seconds
        self.kind = f"{backend.kind}+{cache.kind}-cache"

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        cached = self.cache.get(namespace, key)
        if cached is not None:
            return None if cached.get(self._ABSENT) else cached
        try:
            value = self.backend.get(namespace, key)
        except Exception:
            logger.warning("Session backend read failed for %s; using memory only.", namespace)
            value = None
        if value is None:
            self.cache.set(namespace, key, {self._ABSENT: True}, self.miss_ttl_seconds)
            return None
        # Cache the restored session briefly; the backend still enforces the real expiry.
        self.cache.set(namespace, key, value, self.miss_ttl_seconds)
        return value

    def set(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: float) -> None:
        self.cache.set(namespace, key, value, ttl_seconds)
        try:
            self.backend.set(namespace, key, value, ttl_seconds)
        except Exception:
            logger.warning("Session backend write failed for %s; kept in memory.", namespace)

    def delete(self, namespace: str, key: str) -> None:
        # Remember the deletion so the next read does not ask the backend again.
        self.cache.set(namespace, key, {self._ABSENT: True}, self.miss_ttl_seconds)
        try:
            self.backend.delete(namespace, key)
        except Exception:
            logger.warning("Session backend delete failed for %s.", namespace)

    def status(self) -> dict[str, Any]:
        # Without a working backend the bot still runs, but sessions die with the process.
        return {**self.backend.status(), "kind": self.kind}


def build_session_store(
    supabase_client: SupabaseRestClient | None,
    clock: Callable[[], float] = time,
) -> SessionStore:
    if supabase_client is None:
        return InMemorySessionStore(clock=clock)
    return CachedSessionStore(
        SupabaseSessionStore(supabase_client, clock=clock),
        InMemorySessionStore(clock=clock),
    )


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()
