import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from guard import job_class, needs_queue, starts_dev
from hostconf import HOST_CHECK

ROOT = Path(__file__).parent


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)


class Fixtures(unittest.TestCase):
    """A single-package app, a pnpm monorepo, shell scripts, and harnesses on disk."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="guard-test-")
        root = Path(cls.temp.name)
        cls.app = root / "app"
        write(cls.app / "package.json", json.dumps({"scripts": {
            "dev": "next dev", "build": "next build", "lint": "oxlint .", "typecheck": "tsc --noEmit",
            "test": "vitest", "test:run": "vitest run", "test:coverage": "vitest run --coverage",
            "review:coverage": "pnpm test:coverage && tsx scripts/check-diff-coverage.ts",
            "unit": "vitest run src/lib", "amplify:env": "node scripts/amplify-env.mjs",
            "db:seed": "prisma db seed", "loop": "pnpm loop",
        }}))
        cls.repo = root / "repo"
        write(cls.repo / "pnpm-workspace.yaml", 'packages:\n  - "apps/*"\n\nignoredBuiltDependencies:\n  - sharp\n')
        write(cls.repo / "package.json", json.dumps({"name": "mono", "scripts": {
            "web": "pnpm --filter @mono/web", "test": "turbo run test", "build": "turbo run build",
            "lint": "turbo run lint",
        }}))
        write(cls.repo / "apps/web/package.json", json.dumps({"name": "@mono/web", "scripts": {
            "build": "next build", "test": "vitest run", "lint": "oxlint .",
            "check": "pnpm lint && pnpm test", "quality": "pnpm check",
            "a11y:changed": "tsx scripts/a11y-check.ts", "data:parcels": "tsx scripts/parcels.ts",
            "test:one": "vitest run src/lib/one.test.ts",
        }}))
        write(cls.repo / "apps/api/package.json", json.dumps({"name": "@mono/api", "scripts": {
            "test": "node --import tsx --test 'tests/**/*.test.ts'", "verify-db": "tsx scripts/db.ts",
        }}))
        cls.scripts = root / "scripts"
        write(cls.scripts / "gates.sh", "#!/usr/bin/env bash\nset -euo pipefail\n# per layer\n"
              "for layer in a b; do\n  pnpm exec tsc --noEmit\n  pnpm exec oxlint .\n  pnpm exec vitest run\ndone\n", 0o755)
        write(cls.scripts / "gates", "#!/bin/bash\npnpm exec vitest run\n", 0o755)
        write(cls.scripts / "light.sh", "set -e\necho start # it's fine\npnpm exec oxlint src/a.ts\n")
        write(cls.scripts / "stored.sh", 'test_cmd=${TEST_CMD:-pnpm exec vitest run}\nrun() { "$@"; }\nrun $test_cmd\n')
        write(cls.scripts / "opaque.sh", 'for step in "$@"; do $step; done\n')
        write(cls.scripts / "fanout.sh", "for i in 1 2 3; do node shard.mjs $i & done\nwait\n")
        write(cls.scripts / "variable.sh", 'G="git -C /tmp"\n$G status\nH=' + HOST_CHECK + '\n"$H" pnpm lint\n')
        write(cls.scripts / "selfqueue.sh", 'if [ "${HOST_CHECK_ACTIVE:-}" != 1 ]; then exec host-check bash "$0" "$@"; fi\npnpm exec vitest run\n')
        write(cls.scripts / "env.sh", "export DATABASE_URL=postgres://x\n")
        write(cls.scripts / "bench-render.ts", "console.time('x'); render(); console.timeEnd('x');\n")
        write(cls.scripts / "perf-suite.ts", 'import { execSync } from "node:child_process";\nexecSync("pnpm exec vitest run");\n')
        write(cls.scripts / "debug-1903.ts", 'import { spawnSync } from "node:child_process";\nspawnSync("pnpm", ["exec", "next", "build"]);\n')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()


class GuardTests(Fixtures):
    def test_rejects_unqueued_checks(self):
        for command in [
            "pnpm build", "npm run test", "yarn lint", "bun run typecheck",
            "pnpm --filter app test:unit", "pnpm -r build", "npx vitest run",
            "./node_modules/.bin/tsc --noEmit", "next build", "prettier --check .",
            "VITEST_MAX_WORKERS=2 pnpm test", "env CI=1 pnpm test",
            "nice -n 10 pnpm test", "timeout 10m pnpm build",
            "host-check pnpm build && pnpm test", "host-check pnpm lint | pnpm test",
            "echo host-check; pnpm test", "echo ok\npnpm test",
            "bash -lc 'pnpm lint && pnpm test'", "(pnpm test)",
            "if true; then pnpm build; fi", "pnpm exec vitest run one.test.js",
            # A comment no longer swallows the next line.
            "echo ok # it's done\npnpm test", "{ pnpm test; }",
            # Benchmarks, perf harnesses, debug harnesses, and node's test runner.
            "pnpm exec tsx debug-eng1903.ts", "tsx --expose-gc scripts/bench-tiles.ts",
            "node perf-shards.mjs", "node --import tsx --test 'tests/**/*.test.ts'",
            "bg-job start g -- pnpm check", "bg-job start g pnpm test && bg-job wait g",
            # Command substitutions are commands too, quotes and all.
            "echo \"$(pnpm test)\"", "n=$(pnpm lint | wc -l)",
            "echo \"a: $(curl -s x | grep -oE 'href=\"/e[^\"]*\"')\"; pnpm test",
        ]:
            with self.subTest(command=command):
                self.assertTrue(needs_queue(command))

    def test_allows_queued_checks_and_reads(self):
        for command in [
            "host-check pnpm build", HOST_CHECK + " pnpm test",
            "cd /tmp && host-check pnpm build",
            "host-check bash -lc 'pnpm lint && pnpm test'",
            "host-check pnpm build && host-check pnpm test",
            "rg 'pnpm build' package.json", "echo 'pnpm test'", "git status",
            "pnpm install", "vitest --help", "tsc --version",
            "bash -lc 'host-check pnpm build'",
            "oxlint --version 2>/dev/null", "echo a#b", "cat debug-eng1903.ts",
            "tsx scripts/build-parcels.ts", "rg perf node", "bash /nonexistent/x.sh",
            "H=" + HOST_CHECK + "; \"$H\" pnpm lint",
            "bg-job start g -- host-check pnpm check && bg-job wait g",
            "bg-job status g", "bg-job log g 80", "bg-job wait g",
            # A quote inside `$(...)` opens a new quoting context, not the outer one's end.
            "for b in https://a http://127.0.0.1:3290; do echo \"$b: $(curl -s $b/ | grep -oE "
            "'href=\"/explore[^\"]*\"' | sort | uniq -c | tr '\\n' ' ')\"; done",
            "psql \"$(grep ^DATABASE_URL .env.local | cut -d= -f2- | tr -d '\"')\" -c '\\d \"A\"'",
            "echo \"$(echo ')')\" \"$(printf '%s' \"$(date)\")\"", "echo $((1 + (2 * 3)))",
        ]:
            with self.subTest(command=command):
                self.assertFalse(needs_queue(command))

    def test_resolves_package_scripts(self):
        app, repo, web = str(self.app), str(self.repo), str(self.repo / "apps/web")
        for command, cwd, expected in [
            ("pnpm review:coverage", app, True),
            ("pnpm run review:coverage --base abc", app, True),
            ("npm run review:coverage", app, True),
            ("cd %s && pnpm review:coverage" % app, "/", True),
            ("pnpm -C %s review:coverage" % app, "/", True),
            ("pnpm unit", app, True),
            ("pnpm web quality", repo, True),
            ("pnpm --filter @mono/web a11y:changed", repo, True),
            ("pnpm amplify:env", app, False),
            ("pnpm db:seed", app, False),
            ("pnpm loop", app, False),
            ("pnpm web data:parcels", repo, False),
            ("pnpm review:coverage", "/", False),
            ("host-check pnpm review:coverage", app, False),
        ]:
            with self.subTest(command=command, cwd=cwd):
                self.assertEqual(needs_queue(command, cwd), expected)
        self.assertEqual(needs_queue("pnpm quality", web), True)
        # A `cd` inside a substitution runs in a subshell and leaves the directory alone.
        self.assertEqual(needs_queue('echo "$(cd %s)"; pnpm review:coverage' % app, "/"), False)

    def test_reads_shell_scripts(self):
        s = self.scripts
        for command, expected in [
            (f"bash {s}/gates.sh", True), (f"sh -e {s}/gates.sh", True), (f"{s}/gates.sh", True),
            (f"{s}/gates", True), (f"bash {s}/stored.sh", True), (f"source {s}/light.sh", True),
            (f"bash {s}/opaque.sh", False), (f"bash {s}/selfqueue.sh", False), (f"bash -n {s}/gates.sh", False),
            (f"bash {s}/variable.sh", False), (f"bash -o pipefail {s}/light.sh", True),
            (f"bash -euo pipefail {s}/light.sh", True),
        ]:
            with self.subTest(command=command):
                self.assertEqual(needs_queue(command, str(s)), expected)

    def test_protocols(self):
        for adapter in ["claude", "codex", "cursor", "opencode"]:
            for command, denied in [("pnpm build", True), ("host-check pnpm build", False),
                                    ("pnpm review:coverage", True), ("pnpm amplify:env", False)]:
                payload = {"command": command} if adapter in {"cursor", "opencode"} else {"tool_input": {"command": command}}
                payload["cwd"] = str(self.app)
                result = subprocess.run(
                    ["/usr/bin/python3", str(ROOT / "guard.py"), adapter],
                    input=json.dumps(payload), text=True, capture_output=True, check=False, cwd="/",
                )
                with self.subTest(adapter=adapter, command=command):
                    if adapter == "opencode":
                        self.assertEqual(result.returncode, 2 if denied else 0)
                    elif adapter == "cursor":
                        self.assertEqual(json.loads(result.stdout)["permission"], "deny" if denied else "allow")
                    else:
                        data = json.loads(result.stdout)
                        self.assertEqual(data.get("hookSpecificOutput", {}).get("permissionDecision"), "deny" if denied else None)

    def test_dev_server_ban_follows_host_config(self):
        for deny in (True, False):
            config = Path(self.temp.name) / f"host-{deny}.json"
            config.write_text(json.dumps({"deny_dev_servers": deny}))
            result = subprocess.run(
                ["/usr/bin/python3", str(ROOT / "guard.py"), "claude"],
                input=json.dumps({"tool_input": {"command": "pnpm dev"}}), text=True,
                capture_output=True, check=True, env=dict(os.environ, HOST_CHECK_CONFIG=str(config)),
            )
            decision = json.loads(result.stdout).get("hookSpecificOutput", {}).get("permissionDecision")
            with self.subTest(deny=deny):
                self.assertEqual(decision, "deny" if deny else None)


class DevServerTests(unittest.TestCase):
    def test_dev_servers(self):
        for command, expected in [
            ("next dev", True), ("pnpm dev", True), ("pnpm --filter web dev:turbo", True), ("vite", True),
("bash -lc 'pnpm dev'", True),
            ("tsx scripts/a11y-pages.ts", True), ("pnpm exec tsx scripts/smoke-local.ts", True),
            ("A11Y_BASE_URL=http://localhost:3050 tsx scripts/a11y-pages.ts", False),
            ("bg-job start web -- pnpm dev", True), ("bg-job status web", False),
            ("next start", False), ("vite build", False), ("pnpm build", False), ("prisma migrate dev", False),
            ("echo ok # it's set\nnext dev", True), ("# next dev\necho ok", False), ("pnpm build # then next dev", False),
        ]:
            with self.subTest(command=command):
                self.assertEqual(starts_dev(command), expected)


class ClassTests(Fixtures):
    def test_command_classes(self):
        for command, expected in [
            ("pnpm build", "build"), ("next build", "build"), ("pnpm -r build", "build"),
            ("pnpm test", "heavy"), ("pnpm check", "heavy"), ("vitest run", "heavy"),
            ("npx vitest run", "heavy"), ("playwright test", "heavy"), ("jest", "heavy"),
            ("pnpm test src/a.test.ts", "light"), ("vitest run src/lib/x.test.ts", "light"),
            ("vitest run src/lib", "light"), ("pnpm lint", "light"), ("pnpm typecheck", "light"),
            ("tsc --noEmit", "light"), ("prettier --check .", "light"),
            ("tsx scripts/a11y-pages.ts", "light"), ("njhomes-page-gates a.tsx", "build"),
            ("host-check pnpm build", "build"), ("timeout 10m pnpm test", "heavy"),
            ("bash -lc 'pnpm lint && pnpm test'", "heavy"), ("bash -lc 'pnpm lint && pnpm build'", "build"),
            ("bash -lc 'pnpm lint'", "light"), ("sh -c 'vitest run'", "heavy"),
            # A log path after a redirection is not a test target.
            ("bash -lc 'pnpm test > /tmp/test.log 2>&1'", "heavy"),
            ("vitest run --changed > /tmp/v.log", "heavy"),
            ("vitest --help", "light"),
            # Commands that cannot be seen are heavy, never build.
            ("bash", "heavy"), ("bash -lc 'for c in lint test; do pnpm $c; done'", "heavy"),
            ("bash -lc 'eval \"$CMD\"'", "heavy"), ("bash /nonexistent/gates.sh", "heavy"),
            ("node --test", "heavy"), ("node --import tsx --test 'tests/**/*.test.ts'", "heavy"),
            ("node --test tests/one.test.ts", "light"),
        ]:
            with self.subTest(command=command):
                self.assertEqual(job_class(command, "/"), expected)

    def test_package_script_classes(self):
        app, repo, web, api = str(self.app), str(self.repo), str(self.repo / "apps/web"), str(self.repo / "apps/api")
        for command, cwd, expected in [
            ("pnpm review:coverage", app, "heavy"), ("pnpm run review:coverage --base abc", app, "heavy"),
            ("npm run review:coverage", app, "heavy"), ("pnpm test:run", app, "heavy"),
            ("pnpm test src/a.test.ts", app, "light"), ("pnpm test -- src/a.test.ts", app, "light"),
            ("pnpm unit", app, "light"), ("pnpm amplify:env", app, "light"), ("pnpm loop", app, "light"),
            ("pnpm web build", repo, "build"), ("pnpm web test", repo, "heavy"), ("pnpm web quality", repo, "heavy"),
            # A validation name keeps its class even when the body looks lighter.
            ("pnpm web test:one", repo, "heavy"), ("pnpm --filter @mono/web data:parcels", repo, "light"),
            ("pnpm --filter ./apps/web quality", repo, "heavy"), ("pnpm -F '@mono/*' quality", repo, "heavy"),
            ("pnpm build", repo, "build"), ("turbo run test --filter=@mono/api", repo, "heavy"),
            ("pnpm --filter @mono/api verify-db", repo, "heavy"), ("pnpm test", api, "heavy"),
            ("pnpm quality", web, "heavy"), ("pnpm a11y:changed", web, "light"),
            # Names still decide when the body cannot be found.
            ("pnpm review:coverage", "/", "light"), ("pnpm test", "/", "heavy"), ("pnpm build:data", "/", "build"),
        ]:
            with self.subTest(command=command, cwd=cwd):
                self.assertEqual(job_class(command, cwd), expected)

    def test_shell_script_classes(self):
        s = self.scripts
        for command, expected in [
            (f"bash {s}/gates.sh", "heavy"), (f"{s}/gates.sh", "heavy"), (f"{s}/gates", "heavy"),
            (f"bash {s}/light.sh", "light"), (f"bash {s}/stored.sh", "heavy"), (f"bash {s}/opaque.sh", "heavy"),
            (f"bash {s}/fanout.sh", "heavy"), (f"bash {s}/variable.sh", "light"),
            (f"bash -lc 'source {s}/env.sh && pnpm lint'", "light"), (f"source {s}/missing.sh", "light"),
            (f"bash -n {s}/gates.sh", "light"), (f"bash -x {s}/gates.sh", "heavy"),
        ]:
            with self.subTest(command=command):
                self.assertEqual(job_class(command, str(s)), expected)

    def test_harness_classes(self):
        s = str(self.scripts)
        for command, expected in [
            ("tsx bench-render.ts", "light"), ("pnpm exec tsx perf-suite.ts", "heavy"),
            ("node --import tsx debug-1903.ts", "build"), ("tsx debug-missing.ts", "light"),
        ]:
            with self.subTest(command=command):
                self.assertEqual(job_class(command, s), expected)

    def test_classify_cli(self):
        for argv, cwd, expected in [
            (["pnpm", "review:coverage"], self.app, "heavy"),
            (["bash", str(self.scripts / "gates.sh")], "/", "heavy"),
            (["bash", "-lc", "pnpm lint && pnpm build"], "/", "build"),
            (["pnpm", "lint"], self.app, "light"),
        ]:
            result = subprocess.run(["/usr/bin/python3", str(ROOT / "guard.py"), "--classify", *argv],
                                    cwd=cwd, text=True, capture_output=True, check=True)
            with self.subTest(argv=argv):
                self.assertEqual(result.stdout.strip(), expected)


if __name__ == "__main__":
    unittest.main()
