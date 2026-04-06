import contextlib
import json
import socket
import stat
import threading
from pathlib import Path

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_SCRIPT = Path.home() / ".config" / "lol.pjw.spookycat" / "hook.py"
SOCKET_PATH = "/tmp/spookycat.sock"

HOOK_MARKER = "spookycat"

HOOK_SCRIPT_CONTENT = """\
#!/usr/bin/env python3
import json, os, socket, sys

SOCKET_PATH = "/tmp/spookycat.sock"

def main():
    event = os.environ.get("SPOOKYCAT_EVENT", "unknown")
    try:
        stdin_data = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        stdin_data = {}

    msg = json.dumps({"cwd": os.getcwd(), "event": event, "data": stdin_data})

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(SOCKET_PATH)
        sock.sendall(msg.encode() + b"\\n")
        sock.close()
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        pass

if __name__ == "__main__":
    main()
"""

HOOKS_CONFIG = {
    "UserPromptSubmit": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"SPOOKYCAT_EVENT=prompt_submit python3 {HOOK_SCRIPT}",
                }
            ]
        }
    ],
    "Stop": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": f"SPOOKYCAT_EVENT=stop python3 {HOOK_SCRIPT}",
                }
            ]
        }
    ],
    "PreToolUse": [
        {
            "matcher": "AskUserQuestion",
            "hooks": [
                {
                    "type": "command",
                    "command": f"SPOOKYCAT_EVENT=ask python3 {HOOK_SCRIPT}",
                }
            ],
        }
    ],
}


def _is_spookycat_hook(entry):
    return any(HOOK_MARKER in h.get("command", "") for h in entry.get("hooks", []))


def install_hooks():
    HOOK_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
    HOOK_SCRIPT.write_text(HOOK_SCRIPT_CONTENT)
    HOOK_SCRIPT.chmod(HOOK_SCRIPT.stat().st_mode | stat.S_IEXEC)
    print(f"  Hook script: {HOOK_SCRIPT}")

    if CLAUDE_SETTINGS.exists():
        with CLAUDE_SETTINGS.open() as f:
            settings = json.load(f)
    else:
        CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    hooks = settings.get("hooks", {})

    for event_type in list(hooks.keys()):
        hooks[event_type] = [e for e in hooks[event_type] if not _is_spookycat_hook(e)]
        if not hooks[event_type]:
            del hooks[event_type]

    for event_type, entries in HOOKS_CONFIG.items():
        hooks.setdefault(event_type, []).extend(entries)

    settings["hooks"] = hooks

    with CLAUDE_SETTINGS.open("w") as f:
        json.dump(settings, f, indent=2)

    print(f"  Claude settings: {CLAUDE_SETTINGS}")
    print("Hooks installed.")


def uninstall_hooks():
    if not CLAUDE_SETTINGS.exists():
        print("No Claude settings found.")
        return

    with CLAUDE_SETTINGS.open() as f:
        settings = json.load(f)

    hooks = settings.get("hooks", {})
    removed = False

    for event_type in list(hooks.keys()):
        before = len(hooks[event_type])
        hooks[event_type] = [e for e in hooks[event_type] if not _is_spookycat_hook(e)]
        if len(hooks[event_type]) < before:
            removed = True
        if not hooks[event_type]:
            del hooks[event_type]

    if not hooks and "hooks" in settings:
        del settings["hooks"]

    with CLAUDE_SETTINGS.open("w") as f:
        json.dump(settings, f, indent=2)

    if HOOK_SCRIPT.exists():
        HOOK_SCRIPT.unlink()
        print(f"  Removed {HOOK_SCRIPT}")

    print("Hooks uninstalled." if removed else "No spookycat hooks found.")


class StateServer:
    def __init__(self, on_event):
        self.on_event = on_event
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(SOCKET_PATH)
            sock.close()
        except OSError:
            pass
        if Path(SOCKET_PATH).exists():
            Path(SOCKET_PATH).unlink()

    def _run(self):
        if Path(SOCKET_PATH).exists():
            Path(SOCKET_PATH).unlink()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        server.listen(5)
        server.settimeout(1)

        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
                data = conn.recv(4096).decode().strip()
                conn.close()
                if data:
                    with contextlib.suppress(json.JSONDecodeError):
                        self.on_event(json.loads(data))
            except TimeoutError:
                continue
            except OSError:
                if not self._stop.is_set():
                    raise

        server.close()
        if Path(SOCKET_PATH).exists():
            Path(SOCKET_PATH).unlink()
