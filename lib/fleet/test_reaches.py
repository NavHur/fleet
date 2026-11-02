"""The tailnet policy and each host.json's "reaches" name the same edges.

Run from this directory: python3 -m unittest test_reaches
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

HOSTS = Path(__file__).resolve().parents[2] / "hosts"
# Pedro's own devices: the Mac is the only fleet host among them.
MEMBER_HOSTS = {"mac"}


def policy() -> dict:
    """hosts/tailnet-policy.hujson as JSON: drop // comments and trailing commas."""
    text = re.sub(r"//[^\n]*", "", (HOSTS / "tailnet-policy.hujson").read_text())
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def policy_edges(names: set[str]) -> set[tuple[str, str]]:
    edges = set()
    for grant in policy()["grants"]:
        for src in grant["src"]:
            srcs = MEMBER_HOSTS if src == "autogroup:member" else {src.removeprefix("tag:")}
            for dst in grant["dst"]:
                dsts = names if dst == "*" else {dst.removeprefix("tag:")}
                edges |= {(s, d) for s in srcs for d in dsts if s != d}
    return edges


class Reaches(unittest.TestCase):
    def test_host_json_reaches_matches_the_tailnet_policy(self):
        confs = {conf.parent.name: json.loads(conf.read_text()) for conf in HOSTS.glob("*/host.json")}
        declared = {(name, dst) for name, conf in confs.items() for dst in conf["reaches"]}
        self.assertEqual(declared, policy_edges(set(confs)))

    def test_the_cloud_hosts_reach_nothing(self):
        for name in ("devbox", "workbox"):
            self.assertEqual(json.loads((HOSTS / name / "host.json").read_text())["reaches"], [], name)


if __name__ == "__main__":
    unittest.main()
