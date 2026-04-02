import contextlib
import json
import logging
import shlex
import subprocess
import time
from pathlib import Path

log = logging.getLogger("spookycat")

STATE_FILE = Path.home() / ".local" / "state" / "spookycat.json"

FIND_WINDOW_SCRIPT = """
tell application "System Events"
    tell process "Ghostty"
        repeat with w in every window
            try
                set tabBar to tab group "tab bar" of w
                if (count of radio buttons of tabBar) is {tab_count} then
                    return title of w
                end if
            end try
        end repeat
        return ""
    end tell
end tell
"""

SWITCH_TAB_SCRIPT = """
tell application "System Events"
    tell process "Ghostty"
        set frontmost to true
        repeat with w in every window
            try
                set tabBar to tab group "tab bar" of w
                if (count of radio buttons of tabBar) is {tab_count} then
                    perform action "AXRaise" of w
                    delay 0.1
                    click radio button {tab_index} of tabBar
                    return "ok"
                end if
            end try
        end repeat
        return "not_found"
    end tell
end tell
"""

CLOSE_WINDOW_SCRIPT = """
tell application "Ghostty" to activate
tell application "System Events"
    tell process "Ghostty"
        repeat with w in every window
            try
                set tabBar to tab group "tab bar" of w
                if (count of radio buttons of tabBar) is {tab_count} then
                    perform action "AXRaise" of w
                    delay 0.1
                    keystroke "w" using {{command down, shift down}}
                    return "ok"
                end if
            end try
        end repeat
        return "not_found"
    end tell
end tell
"""


class GhosttyController:
    def __init__(self, tabs):
        self.tabs = tabs
        self.tab_count = len(tabs)

        if self._find_window():
            log.info("Re-attached to existing Ghostty window")
            self._save_state()
        else:
            state = self._load_state()
            if state:
                log.info("Saved window no longer exists, creating new one")
            self._create_window()

    def _load_state(self):
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return None

    def _save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"tab_count": self.tab_count}))

    def _clear_state(self):
        STATE_FILE.unlink(missing_ok=True)

    def _osascript(self, script, timeout=10):
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _find_window(self):
        try:
            title = self._osascript(FIND_WINDOW_SCRIPT.format(tab_count=self.tab_count))
            return bool(title)
        except RuntimeError:
            return False

    def _type_commands(self, commands):
        if not commands:
            return
        lines = []
        for cmd in commands:
            escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'        keystroke "{escaped}"')
            lines.append("        keystroke return")
            lines.append("        delay 0.3")
        script = (
            'tell application "System Events"\n'
            '    tell process "Ghostty"\n' + "\n".join(lines) + "\n"
            "    end tell\n"
            "end tell"
        )
        self._osascript(script, timeout=30)

    def _tab_init(self, tab):
        return [f"cd {shlex.quote(str(tab.workspace))}", *tab.init]

    def _create_window(self):
        subprocess.run(["open", "-a", "Ghostty"], check=True)
        time.sleep(0.5)

        self._osascript(
            'tell application "System Events" to tell process "Ghostty" to '
            'keystroke "n" using command down'
        )
        time.sleep(0.5)

        self._type_commands(self._tab_init(self.tabs[0]))
        time.sleep(0.3)

        for tab in self.tabs[1:]:
            self._osascript(
                'tell application "System Events" to tell process "Ghostty" to '
                'keystroke "t" using command down'
            )
            time.sleep(0.3)
            self._type_commands(self._tab_init(tab))
            time.sleep(0.3)

        self.switch_tab(0)
        self._save_state()
        log.info("Created %d tabs in new Ghostty window", self.tab_count)

    def switch_tab(self, index):
        if not 0 <= index < self.tab_count:
            return
        result = self._osascript(
            SWITCH_TAB_SCRIPT.format(tab_count=self.tab_count, tab_index=index + 1)
        )
        log.debug("switch_tab(%d) → %s", index, result)

    def is_focused(self):
        try:
            result = self._osascript(f"""
tell application "System Events"
    if not (frontmost of process "Ghostty") then return "no"
    tell process "Ghostty"
        try
            set tabBar to tab group "tab bar" of window 1
            if (count of radio buttons of tabBar) is {self.tab_count} then
                return "yes"
            end if
        end try
    end tell
    return "no"
end tell""")
            return result == "yes"
        except RuntimeError:
            return False

    def switch_away(self):
        self._osascript('tell application "System Events" to key code 50 using command down')

    def close(self):
        with contextlib.suppress(RuntimeError):
            self._osascript(CLOSE_WINDOW_SCRIPT.format(tab_count=self.tab_count))
        self._clear_state()
