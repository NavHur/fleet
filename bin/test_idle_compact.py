from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest

loader = importlib.machinery.SourceFileLoader("idle_compact", str(Path(__file__).parent / "idle-compact"))
idle_compact = importlib.util.module_from_spec(importlib.util.spec_from_loader("idle_compact", loader))
loader.exec_module(idle_compact)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def state(threads, provider_threads=(), runs=()):
    """An in-memory T3 state database holding just the projections idle-compact reads."""
    db = sqlite3.connect(":memory:")
    db.executescript("""
        create table orchestration_v2_projection_threads (
            thread_id text, title text, archived_at text, deleted_at text, payload_json text);
        create table orchestration_v2_projection_provider_threads (
            thread_id text, provider text, status text, updated_at text, payload_json text);
        create table orchestration_v2_projection_runs (thread_id text, status text);
    """)
    for thread_id, payload in threads:
        db.execute("insert into orchestration_v2_projection_threads values (?, ?, null, null, ?)",
                   (thread_id, thread_id, json.dumps(payload)))
    for thread_id, status, native in provider_threads:
        db.execute("insert into orchestration_v2_projection_provider_threads values (?, 'claudeAgent', ?, ?, ?)",
                   (thread_id, status, NOW.isoformat(), json.dumps(native)))
    db.executemany("insert into orchestration_v2_projection_runs values (?, ?)", runs)
    return db


def eligible_ids(db):
    found = idle_compact.threads(db)
    parents = idle_compact.busy_parents(found)
    return {t["id"] for t in found if idle_compact.eligible(t, parents, NOW)}


def child(parent):
    return {"lineage": {"parentThreadId": parent}}


IDLE = {"nativeThreadRef": {"nativeId": "session"}, "providerSessionId": "stopped-session"}


class Eligible(unittest.TestCase):
    def test_a_stopped_session_qualifies(self):
        db = state([("parent", {})], [("parent", "idle", IDLE)])
        self.assertEqual(eligible_ids(db), {"parent"})

    def test_a_child_without_a_provider_thread_does_not_block_its_parent(self):
        db = state([("parent", {}), ("native-subagent", child("parent"))], [("parent", "idle", IDLE)])
        self.assertEqual(eligible_ids(db), {"parent"})

    def test_a_running_child_blocks_its_parent(self):
        db = state([("parent", {}), ("worker", child("parent"))],
                   [("parent", "idle", IDLE), ("worker", "idle", {})], runs=[("worker", "running")])
        self.assertEqual(eligible_ids(db), set())

    def test_an_active_provider_thread_is_busy(self):
        db = state([("parent", {})], [("parent", "active", IDLE)])
        self.assertEqual(eligible_ids(db), set())

    def test_a_settled_thread_is_left_alone(self):
        db = state([("parent", {"settledOverride": "settled"})], [("parent", "idle", IDLE)])
        self.assertEqual(eligible_ids(db), set())


if __name__ == "__main__":
    unittest.main()
