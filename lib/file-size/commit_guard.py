"""The agent commit guard: refuse a `git commit` that adds or grows a file over the cap.

guard.py hands commit_refusal each command a hook sees (walk.py leaves), in order. A commit is checked on the index
its chain would leave, so the commands before it that change the index (`git add`, `git restore
--staged`, `git rm --cached`, `git reset`) are replayed on a temporary copy of the real one.
"""
import contextlib
import glob
import os
import re
import shutil
import tempfile
from dataclasses import dataclass

from file_size import GitError, check, decode, failure_message, find_root, git, staged_sides, tracked_sides

# Short `git commit` options whose value may follow in the next word.
COMMIT_VALUE_SHORT = set("mFCct")
# Short `git commit` options whose value can only be attached (`-uall`, `-Skey`): they end a cluster.
COMMIT_ATTACHED_SHORT = set("uS")
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
INDEX_VERBS = {"add", "stage", "restore", "rm", "reset"}
INTERACTIVE_FLAGS = {"-p", "--patch", "-i", "--interactive", "-e", "--edit"}
RESET_MODES = {"--soft", "--mixed", "--hard", "--merge", "--keep"}
# `git reset` modes that rewrite the worktree, which a later `git add` or `commit -a` reads.
WORKTREE_RESETS = {"--hard", "--merge"}
# What a replay returns for a command whose effect on what a later commit records the copy cannot model:
# the commits after it are not checked.
UNKNOWN = object()
# The short options per verb that take a value, which ends a cluster: the rest of the word is the value.
RESTORE_VALUE_SHORT = "s"
VALUE_SHORT = {"restore": RESTORE_VALUE_SHORT}
# The only `git restore` options the replay models, by what they stand for; any other is UNKNOWN.
RESTORE_NAMES = {"-S": "--staged", "--staged": "--staged", "-W": "--worktree", "--worktree": "--worktree",
                 "-q": "--quiet", "--quiet": "--quiet", "--progress": "--progress", "--no-progress": "--progress",
                 "--no-overlay": "--no-overlay", "--source": "--source", "--conflict": "--conflict",
                 "-m": "--merge", "--merge": "--merge", "-2": "--ours", "--ours": "--ours",
                 "-3": "--theirs", "--theirs": "--theirs"}
# The modelled long options that take a value after `=`.
RESTORE_VALUE_LONG = {"--source", "--conflict"}
# What git refuses together with `--staged`, so the real command fails and changes nothing.
RESTORE_REFUSED = {"--merge", "--conflict", "--ours", "--theirs"}
# The only `git rm` options the replay models, by what they stand for; any other is UNKNOWN.
RM_NAMES = {"--cached": "--cached", "--no-cached": "--no-cached", "-r": "-r", "-f": "-f", "--force": "-f",
            "-q": "-q", "--quiet": "-q", "--ignore-unmatch": "--ignore-unmatch", "-n": "-n", "--dry-run": "-n"}
# The ones that still matter once the replay is `rm --cached`.
RM_KEPT = {"-r", "-f", "-q", "--ignore-unmatch"}
# The only `git reset` options the replay models; any other is UNKNOWN.
RESET_OPTIONS = RESET_MODES | {"-q", "--quiet", "--refresh", "--no-refresh"}
# The commands before a commit that the check follows, besides the index verbs: git that only reads, and what
# changes no file (`cd`, `true`, and the shell keywords the walker leaves as words).
READ_ONLY_GIT = {"status", "log", "show", "diff", "rev-parse", "ls-files"}
NO_EFFECT = {"cd", "pushd", "true", "fi", "done", "esac", "for", "case", "select", "}"}
# The verbs whose words the shell expands as pathspecs for git; the others get their words as typed.
GLOB_VERBS = {"add", "stage"}
GLOB_CHARS = set("*?[")
# `git restore`'s source option: `--source=REV`, `--source REV`, `-s REV`, `-sREV`, `-qsREV`; group 1 is an attached value.
SOURCE_OPTION = re.compile(r"(?:--source=|--source(?=$)|-[A-Za-z]*?s)(.*)")
# What the shell expands after the guard reads the command: `$VAR`, a backtick, or the walker's `$(...)` word.
EXPANSION = re.compile(r"[$`]|__substitution__")


@dataclass(frozen=True)
class IndexCommand:
    """An earlier git command in the same chain that may change the index, with the shell's globs expanded
    for `git add`, and the directory git ran in."""
    args: tuple
    directory: str


def git_option_step(words, i, directory):
    """Past the git global option at words[i]: (the next index, the directory after any `-C`)."""
    if words[i] == "-C" and i + 1 < len(words):
        return i + 2, os.path.join(directory, os.path.expanduser(words[i + 1]))
    return i + (2 if words[i] in GIT_VALUE_OPTIONS else 1), directory


def git_subcommand(words, cwd):
    """(The words from the git subcommand on, the directory git runs in), or None."""
    if not words or os.path.basename(words[0]) != "git":
        return None
    i, directory = 1, cwd
    while i < len(words) and words[i].startswith("-"):
        i, directory = git_option_step(words, i, directory)
    return words[i:], directory


def cluster_flags(arg):
    """(Whether a short-option cluster such as -am includes -a, whether its value is the next word)."""
    if not arg.startswith("-") or arg.startswith("--"):
        return False, False
    for j, flag in enumerate(arg[1:]):
        if flag == "a":
            return True, False
        if flag in COMMIT_VALUE_SHORT | COMMIT_ATTACHED_SHORT:  # the rest of the cluster is its value
            return False, flag in COMMIT_VALUE_SHORT and j == len(arg) - 2
    return False, False


def commits_tracked(args):
    """Whether `git commit` arguments stage tracked files first (-a, --all)."""
    words = iter(args)
    for arg in words:
        if arg in ("--", "--all"):
            return arg == "--all"
        has_all, value_next = cluster_flags(arg)
        if has_all:
            return True
        if value_next:
            next(words, None)
    return False


def expand_word(word, cwd):
    """What the shell makes of a word: its glob matches in cwd, sorted, each a `:(literal)` pathspec so git
    does not glob it again, or the word as typed (what the shell hands git) when none match."""
    if word.startswith("-") or not GLOB_CHARS.intersection(word):
        return [word]
    word_path = os.path.expanduser(word)
    base = "" if os.path.isabs(word_path) else cwd
    prefix = os.path.join(base, "")
    matches = sorted(glob.glob(os.path.join(glob.escape(base), word_path)))
    return [f":(literal){match[len(prefix):]}" for match in matches] or [word]


def expand_globs(words, cwd):
    return [expanded for word in words for expanded in expand_word(word, cwd)]


def short_flags(arg, value_short=""):
    """The flag letters of a short-option cluster such as -qS: those before an option that takes a value,
    whose attached value is the rest of the word (`-sWIP`)."""
    if not arg.startswith("-") or arg.startswith("--"):
        return ""
    flags = ""
    for letter in arg[1:]:
        if letter in value_short:
            break
        flags += letter
    return flags


def is_interactive_flag(arg, value_short=""):
    """Flags that ask questions: -p, -i, -e, their long forms, and clusters such as -Ap."""
    return arg in INTERACTIVE_FLAGS or bool(set(short_flags(arg, value_short)) & set("pie"))


def options_of(words):
    """The words before a `--`, which end the options."""
    return words[:words.index("--")] if "--" in words else words


def non_options(words):
    return [word for word in words if not word.startswith("-")]


def commit_id(word, directory):
    """The commit git resolves word to, or None."""
    try:
        return decode(git("rev-parse", "--verify", "-q", f"{word}^{{commit}}", cwd=directory)).strip()
    except GitError:
        return None


def reset_target(rest, directory):
    """(The revision or None, the paths) a `git reset` names; a first word that resolves to a commit is the revision."""
    if "--" in rest:
        words = non_options(options_of(rest))
        return (words[0] if words else None), rest[rest.index("--") + 1:]
    words = non_options(rest)
    if words and commit_id(words[0], directory):
        return words[0], words[1:]
    return None, words


def restore_names(arg):
    """What the options in a `git restore` option word stand for, or None when one is not modelled."""
    if arg.startswith("--"):
        head = arg.partition("=")[0]
        name = RESTORE_NAMES.get(head if head in RESTORE_VALUE_LONG else arg)
        return None if name is None else {name}
    names = [RESTORE_NAMES.get(f"-{letter}") for letter in short_flags(arg, RESTORE_VALUE_SHORT)]
    return None if None in names else set(names)


def parse_restore(rest):
    """(The option names, the revision `git restore` takes its files from or None, the paths), or None when an
    option is not modelled. The value of `--source` or `-s` is no path, and every word after a `--` is."""
    options = options_of(rest)
    words = iter(options)
    names, source, paths = set(), None, []
    for arg in words:
        match = SOURCE_OPTION.fullmatch(arg)
        if match:
            source = match.group(1) or next(words, None)
        if not arg.startswith("-"):
            paths.append(arg)
            continue
        found = restore_names(arg)
        if found is None:
            return None
        names |= found
    return names, source, paths + rest[len(options) + 1:]


def has_glob(words):
    return any(GLOB_CHARS.intersection(word) for word in words if not word.startswith("-"))


def restores_other_than_head(rev, directory):
    """Whether a revision is not HEAD's commit, so unstaging from it can put back a bigger file."""
    return commit_id(rev, directory) != commit_id("HEAD", directory)


def replay_add(rest, directory):
    return ("add", *rest)


def replay_unstaging(source, paths, directory):
    """`git restore --staged` of paths from source, which writes only the index. A glob in paths from another
    revision than HEAD is UNKNOWN: typed unquoted, the shell narrows it, and git's own reading would restore more."""
    if source and has_glob(paths) and restores_other_than_head(source, directory):
        return UNKNOWN
    source_args = [f"--source={source}"] if source else []
    return ("restore", "--staged", *source_args, "--", *paths)


def replay_restore(rest, directory):
    """Only `--staged` without `--worktree` leaves the worktree alone; any other restore is UNKNOWN. It is
    replayed as its source and paths alone, so no option can make the copy write the worktree. One with an
    option that git refuses with `--staged` fails, and changes nothing."""
    parsed = parse_restore(rest)
    if parsed is None:
        return UNKNOWN
    names, source, paths = parsed
    if "--staged" not in names or "--worktree" in names:
        return UNKNOWN
    if names & RESTORE_REFUSED or not paths:
        return None
    return replay_unstaging(source, paths, directory)


def rm_option_words(arg):
    """An option word as the options it stands for: itself, or the letters of a short cluster such as -rf."""
    if arg in RM_NAMES or arg.startswith("--"):
        return [arg]
    return [f"-{letter}" for letter in arg[1:]]


def rm_names(options):
    """What the options of a `git rm` stand for, in order, or None when one is not modelled."""
    words = [word for arg in options if arg.startswith("-") for word in rm_option_words(arg)]
    names = [RM_NAMES.get(word) for word in words]
    return None if None in names else names


def replay_rm(rest, directory):
    """`git rm --cached` rebuilt from the options it models, so the copy never deletes a worktree file. A dry
    run changes nothing; a removal from the worktree, or an option not modelled, is UNKNOWN."""
    options = options_of(rest)
    names = rm_names(options)
    if names is None:
        return UNKNOWN
    if "-n" in names:
        return None
    if [name for name in names if name in ("--cached", "--no-cached")][-1:] != ["--cached"]:
        return UNKNOWN
    paths = non_options(options) + rest[len(options) + 1:]
    return ("rm", "--cached", *sorted(set(names) & RM_KEPT), "--", *paths)


def reset_mode(rest):
    """The mode flag a `git reset` ends with, `--mixed` when it has none."""
    modes = [arg for arg in options_of(rest) if arg in RESET_MODES]
    return modes[-1] if modes else "--mixed"


def replay_pathless_reset(rev, mode, directory):
    """A reset to HEAD as `git read-tree`, which writes only the index (`--soft` changes nothing). One that
    rewrites the worktree, or moves HEAD to another commit or to any commit on an unborn HEAD: UNKNOWN."""
    if mode in WORKTREE_RESETS:
        return UNKNOWN
    head = commit_id("HEAD", directory)
    if rev is not None and (head is None or commit_id(rev, directory) != head):
        return UNKNOWN
    if mode == "--soft":
        return None
    return ("read-tree", "--empty" if head is None else "HEAD")


def replay_reset(rest, directory):
    """`git reset [REV] [--] PATHS` as `git restore --staged`, which cannot move HEAD, and a pathless one
    as `git read-tree`. An option not modelled is UNKNOWN; with paths, git refuses every mode but `--mixed`."""
    if any(arg.startswith("-") and arg not in RESET_OPTIONS for arg in options_of(rest)):
        return UNKNOWN
    mode = reset_mode(rest)
    rev, paths = reset_target(rest, directory)
    if not paths:
        return replay_pathless_reset(rev, mode, directory)
    return replay_unstaging(rev, paths, directory) if mode == "--mixed" else None


REPLAYS = {"add": replay_add, "stage": replay_add, "restore": replay_restore, "rm": replay_rm,
           "reset": replay_reset}


def replay_args(command):
    """The git arguments that make this command's change to a copy of the index and nothing else, UNKNOWN
    for a command the copy cannot model, or None."""
    rest = list(command.args[1:])
    value_short = VALUE_SHORT.get(command.args[0], "")
    if any(is_interactive_flag(arg, value_short) for arg in options_of(rest)):
        return None
    if any(arg.startswith("--pathspec-from-file") for arg in options_of(rest)):
        return UNKNOWN  # the file may not exist yet when the hook runs
    if any(EXPANSION.search(word) for word in rest):
        return UNKNOWN  # the copy cannot know what a `$` expansion builds
    return REPLAYS[command.args[0]](rest, command.directory)


def replays_in(root, changes):
    """(The git arguments, the directory) to replay for each command that changes root's index, or None
    once one is UNKNOWN: the commits after it are not checked."""
    found = []
    for change in changes:
        if find_root(change.directory) != root:
            continue
        args = replay_args(change)
        if args is UNKNOWN:
            return None
        if args:
            found.append((args, change.directory))
    return found


def apply_replay(args, directory, env):
    """Run one command on the copy of the index; one that fails changes nothing, as in the real chain."""
    with contextlib.suppress(GitError):
        git(*args, cwd=directory, env=env)


@contextlib.contextmanager
def replayed_index(root, replays):
    """An env that points git at a temporary copy of root's index with the replays applied in order, or None
    when there are none. The real index, the worktree, and HEAD are not touched."""
    if not replays:
        yield None
        return
    index = decode(git("rev-parse", "--git-path", "index", cwd=root)).strip()
    with tempfile.TemporaryDirectory() as scratch:
        copy = os.path.join(scratch, "index")
        with contextlib.suppress(FileNotFoundError):  # a repository with nothing staged yet has no index
            shutil.copyfile(os.path.join(root, index), copy)
        env = {**os.environ, "GIT_INDEX_FILE": copy}
        for args, directory in replays:
            apply_replay(args, directory, env)
        yield env


def grown_by_commit(args, directory, changes):
    """The files a `git commit` would add or grow past the cap; none outside a repository."""
    root = find_root(directory)
    if root is None:
        return []
    replays = replays_in(root, changes)
    if replays is None:
        return []
    with replayed_index(root, replays) as env:
        comparison = (tracked_sides if commits_tracked(args) else staged_sides)(root, env)
        return check(comparison, root)[0]


def commit_reason(args, directory, changes):
    """Why one `git commit` is refused, or None."""
    try:
        grew = grown_by_commit(args, directory, changes)
    except (GitError, OSError) as exc:
        return f"file-size could not check this commit: {exc}"
    if not grew:
        return None
    return "Commit blocked by the file-size cap.\n" + failure_message(grew)


def command_refusal(args, directory, cwd, changes):
    """Why one git command is refused, or None; one that may change the index is remembered in changes
    for the commits after it. The shell expands its globs in cwd, not in the directory of `git -C`."""
    if args and args[0] in INDEX_VERBS:
        words = expand_globs(args, cwd) if args[0] in GLOB_VERBS else args
        changes.append(IndexCommand(tuple(words), directory))
        return None
    if args[:1] != ["commit"]:
        return None
    return commit_reason(args[1:], directory, changes)


def moves_unreadably(words):
    """Whether words are a `cd` or `pushd` the walker cannot follow: an argument of `-` or a `$` expansion."""
    return words[0] in ("cd", "pushd") and any(word == "-" or EXPANSION.search(word) for word in words[1:])


def is_followed(words, parsed, subshell):
    """Whether the check models a command, given its words and its git subcommand if it is git. What runs in
    a `$(...)` (a commit message from `cat`) counts as following: it is read-only in practice."""
    if subshell:
        return True
    if parsed is None:
        return not words or (words[0] in NO_EFFECT and not moves_unreadably(words))
    args = parsed[0]
    if not args or args[0] in INDEX_VERBS | {"commit"}:
        return True
    return args[0] in READ_ONLY_GIT and not any(arg.startswith("--out") for arg in options_of(args))


def commit_refusal(commands):
    """Why to refuse a command, given its unwrapped simple commands as walk Leafs (read for .words, .cwd, and
    .subshell: in `$(...)`), or None.

    A commit is checked only when every command before it in the line is `cd` or `pushd` to a path it can
    read, `true`, a shell keyword, read-only git (`status`, `log`, `show`, `diff`, `rev-parse`, `ls-files`,
    without `--output`), or a modelled `git add`, `restore`, `rm`, or `reset`; any other command ends the
    check, whatever the repository. ceiling: pathspec commits (`git commit FILE`, `git commit $F`), what a
    `$(...)` runs (taken as read-only), output redirections, and a commit in a directory that is missing or
    not yet a repository when the hook runs are not seen. A `git reset` that moves HEAD or rewrites the
    worktree, a `git restore` or `git rm` that writes the worktree, globs taken from another revision, paths
    read from a file or built by a `$` expansion, and an option the replay does not model end the check for
    the commits after it in that repository. A quoted glob in `git add` that matches below the current
    directory is read as the shell's narrower expansion. An unquoted glob in `git reset`, `git restore
    --staged`, or `git rm --cached` goes to git as typed, so the replay also unstages its matches below the
    current directory. The pre-commit skill and CI run `check --base` as the backstop.
    """
    changes = []
    for leaf in commands:
        parsed = git_subcommand(leaf.words, leaf.cwd)
        if not is_followed(leaf.words, parsed, leaf.subshell):
            return None
        reason = parsed and command_refusal(*parsed, leaf.cwd, changes)
        if reason:
            return reason
    return None
