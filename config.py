import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "lol.pjw.spookycat"
CONFIG_FILE = CONFIG_DIR / "spookycat.toml"

SAMPLE_CONFIG = """\
# SpookyCat — Stream Deck Mini configuration
# Each [[tabs]] entry maps a Stream Deck key (0-5) to a Ghostty tab.
#
# icon: displayed on the button — unicode char, emoji, or short string (1-3 chars)
# init: shell commands to run when the tab is first created

[[tabs]]
key = 0
icon = "α"
init = ["echo 'Tab 1 ready'"]

[[tabs]]
key = 1
icon = "β"
init = ["echo 'Tab 2 ready'"]

[[tabs]]
key = 2
icon = "γ"
init = ["echo 'Tab 3 ready'"]

[[tabs]]
key = 3
icon = "δ"
init = ["echo 'Tab 4 ready'"]

[[tabs]]
key = 4
icon = "ε"
init = ["echo 'Tab 5 ready'"]

[[tabs]]
key = 5
icon = "ζ"
init = ["echo 'Tab 6 ready'"]
"""


@dataclass
class TabConfig:
    key: int
    icon: str
    init: list[str]


def load_config() -> list[TabConfig]:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(SAMPLE_CONFIG)
        print(f"Created sample config at {CONFIG_FILE}")
        print(f"Go ahead and make it yours: $EDITOR {CONFIG_FILE}")
        sys.exit(0)

    with CONFIG_FILE.open("rb") as f:
        raw = tomllib.load(f)

    tabs_raw = raw.get("tabs", [])
    if not tabs_raw:
        print(f"Error: no [[tabs]] entries in {CONFIG_FILE}")
        sys.exit(1)

    tabs = []
    seen_keys = set()
    for entry in tabs_raw:
        key = entry.get("key")
        if key is None:
            print("Error: tab entry missing 'key'")
            sys.exit(1)
        if not isinstance(key, int) or not 0 <= key <= 5:
            print(f"Error: key {key} is invalid (must be integer 0-5)")
            sys.exit(1)
        if key in seen_keys:
            print(f"Error: duplicate key {key}")
            sys.exit(1)
        seen_keys.add(key)

        icon = entry.get("icon", "?")
        init_cmds = entry.get("init", [])
        if not isinstance(init_cmds, list):
            print(f"Error: 'init' for key {key} must be an array")
            sys.exit(1)

        tabs.append(TabConfig(key=key, icon=icon, init=init_cmds))

    tabs.sort(key=lambda t: t.key)
    return tabs
