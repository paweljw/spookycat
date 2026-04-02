import logging
import re
import subprocess
import threading

log = logging.getLogger("spookycat")


class Poller:
    """Runs registered callbacks per workspace on an interval.

    Each callback: fn(workspace: Path) -> dict[str, Any] | None
    Results are forwarded to on_update(workspace, key, value).
    """

    def __init__(self, interval, workspaces, on_update):
        self.interval = interval
        self.workspaces = workspaces
        self.on_update = on_update
        self.callbacks = []
        self.pre_cycle_hooks = []
        self._thread = None
        self._stop = threading.Event()

    def register(self, callback):
        self.callbacks.append(callback)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            for hook in self.pre_cycle_hooks:
                hook()
            for workspace in self.workspaces:
                for callback in self.callbacks:
                    try:
                        result = callback(workspace)
                        if result:
                            for key, value in result.items():
                                self.on_update(workspace, key, value)
                    except Exception:
                        pass
            self._stop.wait(self.interval)


_claude_cwds_cache = None
_claude_cwds_lock = threading.Lock()


def _get_claude_cwds():
    """Get working directories of all Claude-related processes. Cached per poll cycle."""
    global _claude_cwds_cache
    with _claude_cwds_lock:
        if _claude_cwds_cache is not None:
            return _claude_cwds_cache

    try:
        result = subprocess.run(
            ["pgrep", "-x", "claude"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return set()

    if result.returncode != 0:
        return set()

    cwds = set()
    for pid in result.stdout.strip().split("\n"):
        pid = pid.strip()
        if not pid:
            continue
        try:
            lsof = subprocess.run(
                ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in lsof.stdout.split("\n"):
                if line.startswith("n/"):
                    cwds.add(line[1:])
        except Exception:
            pass

    with _claude_cwds_lock:
        _claude_cwds_cache = cwds
    if cwds:
        log.debug("poll: claude cwds: %s", cwds)
    return cwds


def invalidate_claude_cache():
    """Call at the start of each poll cycle to refresh the process cache."""
    global _claude_cwds_cache
    with _claude_cwds_lock:
        _claude_cwds_cache = None


MAX_SUBTITLE = 7
TICKET_RE = re.compile(r"^([a-zA-Z]+-\d+)")


def _format_branch(branch):
    """Format a git branch name into a short subtitle."""
    if "/" in branch:
        branch = branch.split("/", 1)[1]

    ticket = TICKET_RE.match(branch)
    if ticket:
        return ticket.group(1).upper()

    if len(branch) <= MAX_SUBTITLE:
        return branch
    return branch[: MAX_SUBTITLE - 1] + "~"


def check_git_branch(workspace):
    """Get the current git branch or short SHA for a workspace."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    branch = result.stdout.strip()

    if branch == "HEAD":
        try:
            sha = subprocess.run(
                ["git", "-C", str(workspace), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return {"git_subtitle": sha.stdout.strip()[:MAX_SUBTITLE]}
        except Exception:
            return {"git_subtitle": "detach"}

    return {"git_subtitle": _format_branch(branch)}


def check_claude_process(workspace):
    """Check if a Claude process is running with cwd in this workspace."""
    cwds = _get_claude_cwds()
    workspace_str = str(workspace)
    for cwd in cwds:
        if cwd == workspace_str or cwd.startswith(workspace_str + "/"):
            return {"claude_running": True}
    return {"claude_running": False}
