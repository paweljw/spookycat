import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

CONFIG_DIR = Path.home() / ".config" / "lol.pjw.spookycat"
CONFIG_FILE = CONFIG_DIR / "spookycat.toml"

SAMPLE_CONFIG = """\
# SpookyCat — Stream Deck Mini configuration

[settings]
poll_interval = 5  # seconds between workspace state polls

[colors]
inactive = "#000000"   # no Claude running (black)
working = "#2980b9"    # Claude is processing (blue)
done = "#27ae60"       # Claude finished (green)
asking = "#c0392b"     # Claude needs attention (red)

# Each [[tabs]] maps a Stream Deck key (0-5) to a Ghostty tab.
# workspace: directory to cd into on tab creation (required)
# icon: shown on button — unicode char, emoji, or short string (1-3 chars)
# init: commands to run AFTER cd to workspace (optional, default [])

[[tabs]]
key = 0
icon = "α"
workspace = "~/projects/alpha"
init = ["echo 'ready'"]

[[tabs]]
key = 1
icon = "β"
workspace = "~/projects/beta"
init = []

[[tabs]]
key = 2
icon = "γ"
workspace = "~/projects/gamma"
init = []

[[tabs]]
key = 3
icon = "δ"
workspace = "~/projects/delta"
init = []

[[tabs]]
key = 4
icon = "ε"
workspace = "~/projects/epsilon"
init = []

[[tabs]]
key = 5
icon = "ζ"
workspace = "~/projects/zeta"
init = []
"""


@dataclass
class TabConfig:
    key: int
    icon: str
    workspace: Path
    init: list[str]


@dataclass
class Colors:
    inactive: str = "#000000"
    working: str = "#2980b9"
    done: str = "#27ae60"
    asking: str = "#c0392b"


@dataclass
class SpookyCatConfig:
    tabs: list[TabConfig]
    colors: Colors = field(default_factory=Colors)
    poll_interval: int = 5


def load_config() -> SpookyCatConfig:
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(SAMPLE_CONFIG)
        print(f"Created sample config at {CONFIG_FILE}")
        print(f"Go ahead and make it yours: $EDITOR {CONFIG_FILE}")
        sys.exit(0)

    with CONFIG_FILE.open("rb") as f:
        raw = tomllib.load(f)

    settings = raw.get("settings", {})
    poll_interval = settings.get("poll_interval", 5)

    colors_raw = raw.get("colors", {})
    for name, value in colors_raw.items():
        if not HEX_COLOR_RE.match(value):
            print(f"Error: color '{name}' must be hex like #RRGGBB, got '{value}'")
            sys.exit(1)
    colors = Colors(
        inactive=colors_raw.get("inactive", Colors.inactive),
        working=colors_raw.get("working", Colors.working),
        done=colors_raw.get("done", Colors.done),
        asking=colors_raw.get("asking", Colors.asking),
    )

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

        workspace_str = entry.get("workspace")
        if not workspace_str:
            print(f"Error: tab {key} missing 'workspace'")
            sys.exit(1)

        tabs.append(
            TabConfig(
                key=key,
                icon=entry.get("icon", "?"),
                workspace=Path(workspace_str).expanduser().resolve(),
                init=entry.get("init", []),
            )
        )

    tabs.sort(key=lambda t: t.key)
    return SpookyCatConfig(tabs=tabs, colors=colors, poll_interval=poll_interval)


def print_sample_config():
    print(SAMPLE_CONFIG)
