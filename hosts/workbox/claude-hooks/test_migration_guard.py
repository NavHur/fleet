"""Run with: cd hosts/workbox/claude-hooks && python3 -m unittest test_migration_guard"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("migration_guard", Path(__file__).with_name("migration-guard.py"))
migration_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration_guard)

SHARED = "postgresql://app:pw@db.example.rds.amazonaws.com:5432/app?sslmode=require"
LOCAL = "postgresql://app@127.0.0.1:55440/app_test"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class MigrationGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="migration-guard-")
        root = Path(cls.temp.name)
        cls.shared = root / "shared"
        write(cls.shared / "package.json", json.dumps({"scripts": {"web": "pnpm --filter web", "migrate:prod": "prisma migrate deploy"}}))
        write(cls.shared / "pnpm-workspace.yaml", "packages:\n  - apps/*\n")
        write(cls.shared / "apps/web/package.json", json.dumps({"name": "web", "scripts": {
            "db:deploy": "prisma migrate deploy", "db:seed": "tsx seed.ts", "db:migrate": "node scripts/migrate.mjs"}}))
        write(cls.shared / "apps/web/.env", f'DATABASE_URL="{SHARED}"\n')
        cls.web = cls.shared / "apps/web"
        write(cls.web / "migrate.sh", "#!/usr/bin/env bash\npnpm exec prisma migrate deploy\n")
        cls.local = root / "local"
        write(cls.local / "package.json", json.dumps({"scripts": {"db:deploy": "prisma migrate deploy"}}))
        write(cls.local / ".env", f"DATABASE_URL={SHARED}\n")
        write(cls.local / ".env.local", f"DATABASE_URL={LOCAL}\n")
        cls.bare = root / "bare"
        cls.bare.mkdir()
        cls.monorepo = root / "monorepo"  # a workspace root with no .env: only the package has one
        write(cls.monorepo / "package.json", json.dumps({"private": True, "scripts": {"api": "pnpm --filter api"}}))
        write(cls.monorepo / "pnpm-workspace.yaml", "packages:\n  - packages/*\n")
        write(cls.monorepo / "packages/api/package.json",
              json.dumps({"name": "api", "scripts": {"db:migrate": "prisma migrate deploy"}}))
        write(cls.monorepo / "packages/api/.env", f"DATABASE_URL={LOCAL}\n")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def transcript(self, message):
        path = Path(self.temp.name) / "transcript.jsonl"
        entries = [{"type": "user", "message": {"role": "user", "content": message}}] if message else []
        path.write_text("".join(json.dumps(e) + "\n" for e in entries))
        return str(path)

    def denied(self, command, cwd, message=None, **extra):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
                   "tool_input": {"command": command}, "transcript_path": self.transcript(message), **extra}
        return migration_guard.reason(command, payload)

    def test_holds_migrations_on_a_shared_database(self):
        for command, cwd in [
            ("pnpm exec prisma migrate deploy", self.web),
            ("npx prisma db push", self.web),
            ("host-check pnpm db:deploy", self.web),
            ("pnpm web db:deploy", self.shared),
            ("pnpm migrate:prod", self.shared),
            ("cd %s && ./node_modules/.bin/prisma migrate resolve --applied x" % self.web, "/"),
            ("host-check bash -lc 'pnpm db:deploy && pnpm build'", self.web),
            ('echo "$(cd %s && pnpm exec prisma migrate deploy)"' % self.web, "/"),
            (f"DATABASE_URL='{SHARED}' pnpm exec prisma migrate deploy", self.bare),
            ("pnpm exec prisma migrate deploy", self.bare),  # no URL found: unknown counts as shared
            ("bash migrate.sh", self.web),
            ("env -u CI timeout -s KILL 60 pnpm exec prisma migrate deploy", self.web),
            ("pnpm db:migrate", self.web),  # held by its name whatever tool the body runs
            ("pnpm db:push", self.web),  # no such script: still held by name
            ("pnpm run db:push", self.web),
            ("yarn db:push", self.web),
        ]:
            with self.subTest(command=command):
                self.assertIsNotNone(self.denied(command, cwd))

    def test_allows_reads_and_local_databases(self):
        for command, cwd in [
            ("pnpm exec prisma migrate status", self.web),
            ("pnpm exec prisma migrate diff --from-config-datasource --to-schema prisma/schema.prisma --script", self.web),
            ("pnpm db:seed", self.web),
            ("rg db:deploy package.json", self.web),
            ("npx prisma migrate deploy --help", self.web),
            ("pnpm exec prisma migrate deploy", self.local),  # .env.local wins over .env
            (f"DATABASE_URL={LOCAL} pnpm exec prisma migrate deploy", self.web),
            ("DATABASE_URL=postgresql://u@localhost/x?host=/var/run/postgresql prisma migrate dev", self.web),
            ("DATABASE_URL=file:./dev.db prisma db push", self.bare),
        ]:
            with self.subTest(command=command):
                self.assertIsNone(self.denied(command, cwd))

    def test_a_workspace_runner_is_judged_by_the_package_it_selects(self):
        for command in ("pnpm --filter api db:migrate", "pnpm api db:migrate"):
            with self.subTest(command=command):
                self.assertIsNone(self.denied(command, self.monorepo))
        self.assertIsNotNone(self.denied("pnpm exec prisma migrate deploy", self.monorepo))

    def test_chat_approval(self):
        command = "pnpm exec prisma migrate deploy"
        self.assertIsNone(self.denied(command, self.web, "I authorize the migration"))
        self.assertIsNone(self.denied(command, self.web, "migrate"))
        self.assertIsNotNone(self.denied(command, self.web, "don't migrate yet"))
        self.assertIsNotNone(self.denied(command, self.web, "merge 781"))
        reason = self.denied(command, self.web, "I authorize the migration", agent_id="a1")
        self.assertIn("Subagents", reason)
        self.assertIn("db.example.rds.amazonaws.com", self.denied(command, self.web))


if __name__ == "__main__":
    unittest.main()
