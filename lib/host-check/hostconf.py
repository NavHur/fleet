"""This machine's host-check settings, from ~/.config/fleet/host.json.

bin/sync links that file to hosts/<machine>/host.json in the fleet repo.
HOST_CHECK_CONFIG points at another file, for tests.
"""
import json
import os

DEFAULTS = {
    "slots": 4,               # jobs at once, host-wide
    "heavy_slots": 2,         # of those, whole suites and builds
    "build_slots": 1,         # of those, builds
    "vitest_max_workers": 2,  # default VITEST_MAX_WORKERS inside the queue
    "nice": 0,                # nice level for jobs (Linux slice or fallback)
    "slice": None,            # Linux: systemd user slice for jobs
    "qos_clamp": None,        # macOS: taskpolicy QoS clamp for jobs
    "deny_dev_servers": False,
}

HOST_CHECK = os.path.expanduser("~/.local/bin/host-check")
HOST_VALIDATION = os.path.expanduser("~/.config/host-validation.md")


def previews_path():
    """The worktree preview recipes bin/preview-worktree reads; only hosts that serve previews have one."""
    return os.environ.get("PREVIEW_WORKTREE_CONFIG") or os.path.expanduser("~/.config/fleet/previews.json")


def path():
    return os.environ.get("HOST_CHECK_CONFIG") or os.path.expanduser("~/.config/fleet/host.json")


def load():
    conf = dict(DEFAULTS)
    try:
        with open(path()) as handle:
            conf.update(json.load(handle))
    except FileNotFoundError:
        pass
    return conf
