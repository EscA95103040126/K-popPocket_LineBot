from __future__ import annotations

import pytest

from src.bot.container import build_bot
from src.bot.dispatcher import MessageContext
from src.bot.sessions import (
    CachedSessionStore,
    InMemorySessionStore,
    SupabaseSessionStore,
    build_session_store,
)
from tests.fakes import make_app, make_deps

NOW = 1_760_000_000.0  # 2025-10-09T08:53:20+00:00


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class RecordingSupabaseClient:
    def __init__(self, rows: list[dict] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[dict] = []

    def request(self, method, table, *, params=None, json_payload=None, prefer=None):
        self.calls.append(
            {
                "method": method,
                "table": table,
                "params": params,
                "json": json_payload,
                "prefer": prefer,
            }
        )
        if self.error is not None:
            raise self.error
        return self.rows if method == "GET" else None


class CountingStore(InMemorySessionStore):
    """An in-memory 'durable' backend that counts reads and can be made to fail."""

    kind = "durable"

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock=clock)
        self.reads = 0
        self.failing = False

    def get(self, namespace, key):
        self.reads += 1
        if self.failing:
            raise ConnectionError("backend down")
        return super().get(namespace, key)

    def set(self, namespace, key, value, ttl_seconds):
        if self.failing:
            raise ConnectionError("backend down")
        super().set(namespace, key, value, ttl_seconds)

    def delete(self, namespace, key):
        if self.failing:
            raise ConnectionError("backend down")
        super().delete(namespace, key)


# --- InMemorySessionStore ---------------------------------------------------------


def test_memory_store_round_trip_and_delete() -> None:
    store = InMemorySessionStore(clock=Clock())

    store.set("quiz", "u1", {"step": 1}, ttl_seconds=60)

    assert store.get("quiz", "u1") == {"step": 1}
    assert store.get("other", "u1") is None
    store.delete("quiz", "u1")
    assert store.get("quiz", "u1") is None


def test_memory_store_expires_after_ttl() -> None:
    clock = Clock()
    store = InMemorySessionStore(clock=clock)
    store.set("quiz", "u1", {"step": 1}, ttl_seconds=60)

    clock.now += 60
    assert store.get("quiz", "u1") == {"step": 1}
    clock.now += 1
    assert store.get("quiz", "u1") is None


def test_memory_store_returns_copies() -> None:
    store = InMemorySessionStore(clock=Clock())
    value = {"answers": ["女團"]}
    store.set("quiz", "u1", value, ttl_seconds=60)

    value["answers"].append("changed after set")
    store.get("quiz", "u1")["answers"].append("changed after get")

    assert store.get("quiz", "u1") == {"answers": ["女團"]}


def test_memory_store_evicts_least_recently_written_entry() -> None:
    store = InMemorySessionStore(clock=Clock(), max_entries=2)
    store.set("quiz", "a", {}, ttl_seconds=60)
    store.set("quiz", "b", {}, ttl_seconds=60)
    store.set("quiz", "a", {"refreshed": True}, ttl_seconds=60)

    store.set("quiz", "c", {}, ttl_seconds=60)

    assert store.get("quiz", "b") is None
    assert store.get("quiz", "a") == {"refreshed": True}
    assert store.get("quiz", "c") == {}


# --- SupabaseSessionStore ---------------------------------------------------------


def test_supabase_store_upserts_with_expiry() -> None:
    client = RecordingSupabaseClient()
    store = SupabaseSessionStore(client, clock=Clock())

    store.set("bias_radar", "U1", {"question_index": 2}, ttl_seconds=1800)

    (call,) = client.calls
    assert call["method"] == "POST"
    assert call["table"] == "bot_sessions"
    assert call["params"] == {"on_conflict": "namespace,session_key"}
    assert call["prefer"] == "resolution=merge-duplicates,return=minimal"
    assert call["json"] == {
        "namespace": "bias_radar",
        "session_key": "U1",
        "payload": {"question_index": 2},
        "expires_at": "2025-10-09T09:23:20+00:00",
        "updated_at": "2025-10-09T08:53:20+00:00",
    }


def test_supabase_store_reads_only_unexpired_rows() -> None:
    client = RecordingSupabaseClient(rows=[{"payload": {"question_index": 2}}])
    store = SupabaseSessionStore(client, clock=Clock())

    assert store.get("bias_radar", "U1") == {"question_index": 2}
    assert client.calls[0]["params"] == {
        "select": "payload",
        "namespace": "eq.bias_radar",
        "session_key": "eq.U1",
        "expires_at": "gt.2025-10-09T08:53:20+00:00",
        "limit": "1",
    }


def test_supabase_store_returns_none_without_row() -> None:
    store = SupabaseSessionStore(RecordingSupabaseClient(rows=[]), clock=Clock())

    assert store.get("bias_radar", "U1") is None


def test_supabase_store_deletes_by_namespace_and_key() -> None:
    client = RecordingSupabaseClient()

    SupabaseSessionStore(client, clock=Clock()).delete("bias_radar", "U1")

    assert client.calls[0]["method"] == "DELETE"
    assert client.calls[0]["params"] == {"namespace": "eq.bias_radar", "session_key": "eq.U1"}


# --- CachedSessionStore -----------------------------------------------------------


def _cached(clock: Clock, backend: CountingStore) -> CachedSessionStore:
    return CachedSessionStore(backend, InMemorySessionStore(clock=clock))


def test_cached_store_serves_own_writes_from_memory() -> None:
    clock = Clock()
    backend = CountingStore(clock)
    store = _cached(clock, backend)

    store.set("quiz", "u1", {"step": 1}, ttl_seconds=60)

    assert store.get("quiz", "u1") == {"step": 1}
    assert backend.reads == 0


def test_cached_store_restores_from_backend_after_restart() -> None:
    clock = Clock()
    backend = CountingStore(clock)
    _cached(clock, backend).set("quiz", "u1", {"step": 3}, ttl_seconds=60)

    restarted = _cached(clock, backend)

    assert restarted.get("quiz", "u1") == {"step": 3}
    assert restarted.get("quiz", "u1") == {"step": 3}
    assert backend.reads == 1


def test_cached_store_remembers_misses() -> None:
    clock = Clock()
    backend = CountingStore(clock)
    store = _cached(clock, backend)

    assert store.get("quiz", "nobody") is None
    assert store.get("quiz", "nobody") is None
    assert backend.reads == 1


def test_cached_store_delete_does_not_resurrect_from_backend() -> None:
    clock = Clock()
    backend = CountingStore(clock)
    store = _cached(clock, backend)
    store.set("quiz", "u1", {"step": 1}, ttl_seconds=60)

    store.delete("quiz", "u1")

    assert store.get("quiz", "u1") is None
    assert backend.reads == 0


def test_cached_store_keeps_working_when_backend_fails() -> None:
    clock = Clock()
    backend = CountingStore(clock)
    backend.failing = True
    store = _cached(clock, backend)

    assert store.get("quiz", "u1") is None
    store.set("quiz", "u1", {"step": 1}, ttl_seconds=60)
    assert store.get("quiz", "u1") == {"step": 1}
    store.delete("quiz", "u1")
    assert store.get("quiz", "u1") is None


def test_build_session_store_picks_backend_from_configuration() -> None:
    assert build_session_store(None).kind == "memory"
    assert build_session_store(RecordingSupabaseClient()).kind == "supabase+memory-cache"


# --- surviving a restart end to end -------------------------------------------------


@pytest.fixture
def durable():
    clock = Clock()
    return clock, CountingStore(clock)


def _bot_after_restart(clock: Clock, backend: CountingStore):
    return build_bot(make_deps(clock=clock, sessions=_cached(clock, backend)))


def test_bias_radar_progress_survives_restart(durable) -> None:
    clock, backend = durable
    before = _bot_after_restart(clock, backend).dispatcher
    before.dispatch(MessageContext(text="本命雷達測驗", user_id="U-restart"))
    before.dispatch(MessageContext(text="本命雷達:0:女團", user_id="U-restart"))

    after = _bot_after_restart(clock, backend).dispatcher
    reply = after.dispatch(MessageContext(text="本命雷達:1:小鹿", user_id="U-restart"))

    assert reply.report.startswith("本命雷達測驗 Q3/5")


def test_ai_curator_follow_up_context_survives_restart(durable) -> None:
    clock, backend = durable
    before = _bot_after_restart(clock, backend).features.ai_curator
    before._store_ai_curator_reason_context("U-restart", [{"artist": "NMIXX", "member": "JIWOO"}])

    after = _bot_after_restart(clock, backend).features.ai_curator

    assert after._ai_curator_reason_context_members("U-restart") == [
        {"artist": "NMIXX", "member": "JIWOO"}
    ]


def test_health_reports_session_store() -> None:
    payload = make_app().test_client().get("/health").get_json()

    assert payload["session_store"] == {"kind": "memory", "ok": True}


def test_session_status_reports_missing_supabase_table() -> None:
    client = RecordingSupabaseClient(error=RuntimeError('relation "bot_sessions" does not exist'))

    status = build_session_store(client).status()

    assert status["kind"] == "supabase+memory-cache"
    assert status["ok"] is False
    assert "bot_sessions" in status["error"]


def test_session_status_reports_reachable_supabase_table() -> None:
    status = build_session_store(RecordingSupabaseClient(rows=[])).status()

    assert status == {"kind": "supabase+memory-cache", "ok": True}
