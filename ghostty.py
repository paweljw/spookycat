import contextlib
import json
import subprocess
import time
from pathlib import Path

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
tell application "Ghostty" to activate
tell application "System Events"
    tell process "Ghostty"
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
    TAB_COUNT = 6

    def __init__(self):
        if self._find_window():
            print("  Re-attached to existing Ghostty window")
            self._save_state()
        else:
            state = self._load_state()
            if state:
                print("  Saved window no longer exists, creating new one")
            self._create_window()

    def _load_state(self):
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return None

    def _save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"tab_count": self.TAB_COUNT}))

    def _clear_state(self):
        STATE_FILE.unlink(missing_ok=True)

    def _osascript(self, script):
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _find_window(self):
        try:
            title = self._osascript(FIND_WINDOW_SCRIPT.format(tab_count=self.TAB_COUNT))
            return bool(title)
        except RuntimeError:
            return False

    def _create_window(self):
        subprocess.run(["open", "-a", "Ghostty"], check=True)
        time.sleep(0.5)

        self._osascript(
            'tell application "System Events" to tell process "Ghostty" to '
            'keystroke "n" using command down'
        )
        time.sleep(0.5)

        for _ in range(self.TAB_COUNT - 1):
            self._osascript(
                'tell application "System Events" to tell process "Ghostty" to '
                'keystroke "t" using command down'
            )
            time.sleep(0.3)

        self.switch_tab(0)
        self._save_state()
        print(f"  Created {self.TAB_COUNT} tabs in new Ghostty window")

    def switch_tab(self, index):
        if not 0 <= index < self.TAB_COUNT:
            return
        self._osascript(SWITCH_TAB_SCRIPT.format(tab_count=self.TAB_COUNT, tab_index=index + 1))

    def close(self):
        with contextlib.suppress(RuntimeError):
            self._osascript(CLOSE_WINDOW_SCRIPT.format(tab_count=self.TAB_COUNT))
        self._clear_state()
