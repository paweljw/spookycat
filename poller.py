import subprocess
import threading


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
            ["pgrep", "-f", "claude"],
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
                ["lsof", "-p", pid, "-d", "cwd", "-Fn"],
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
        print(f"  [poll] claude cwds: {cwds}")
    return cwds


def invalidate_claude_cache():
    """Call at the start of each poll cycle to refresh the process cache."""
    global _claude_cwds_cache
    with _claude_cwds_lock:
        _claude_cwds_cache = None


def check_claude_process(workspace):
    """Check if a Claude process is running with cwd in this workspace."""
    cwds = _get_claude_cwds()
    workspace_str = str(workspace)
    for cwd in cwds:
        if cwd == workspace_str or cwd.startswith(workspace_str + "/"):
            return {"claude_running": True}
    return {"claude_running": False}
