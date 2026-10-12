from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

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


class Hooks(BaseHTTPRequestHandler):
    """Records each request, answering like T3's webhook route."""
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["content-length"]))
        Hooks.received.append((self.path, json.loads(body)))
        self.send_response(202)
        self.send_header("x-t3-hook-outcome", "accepted")
        self.end_headers()

    def log_message(self, *args):
        pass


class Wake(unittest.TestCase):
    """`wake` against a T3 state directory on disk and a local stand-in for T3's server."""

    def setUp(self):
        Hooks.received = []
        self.server = HTTPServer(("127.0.0.1", 0), Hooks)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "server-runtime.json").write_text(json.dumps({"origin": f"http://127.0.0.1:{self.server.server_port}"}))
        self.db = sqlite3.connect(root / "statev2.sqlite")
        self.db.execute("create table scheduled_tasks (task_id text, title text, enabled integer, webhook_token text)")
        patch = mock.patch.object(idle_compact, "STATE", root / "statev2.sqlite")
        patch.start()
        self.addCleanup(patch.stop)

    def task(self, title="Idle compaction", enabled=1, token="tok123"):
        self.db.execute("insert into scheduled_tasks values ('scheduled-task:abc', ?, ?, ?)", (title, enabled, token))
        self.db.commit()

    def wake(self, due):
        with mock.patch.object(idle_compact, "pick", return_value=due):
            return idle_compact.wake()

    def test_a_due_thread_posts_to_the_janitor_webhook(self):
        self.task()
        self.assertEqual(self.wake([{"threadId": "a"}, {"threadId": "b"}]), 0)
        self.assertEqual(Hooks.received, [("/api/hooks/scheduled-task%3Aabc/tok123", {"due": 2})])

    def test_nothing_due_posts_nothing(self):
        self.task()
        self.assertEqual(self.wake([]), 0)
        self.assertEqual(Hooks.received, [])

    def test_an_interval_task_is_not_a_webhook(self):
        self.task(token=None)
        self.assertEqual(self.wake([{"threadId": "a"}]), 1)
        self.assertEqual(Hooks.received, [])

    def test_a_disabled_task_is_skipped(self):
        self.task(enabled=0)
        self.assertEqual(self.wake([{"threadId": "a"}]), 1)
        self.assertEqual(Hooks.received, [])


if __name__ == "__main__":
    unittest.main()
