# SpookyCat

Custom Elgato Stream Deck Mini controller for managing multiple Claude Code workspaces in Ghostty.

Each button maps to a Ghostty tab with a dedicated workspace. Buttons show the workspace icon, git branch info, and Claude's current state via color:

- **Black** -- no Claude running
- **Green** -- Claude idle/ready
- **Blue** -- Claude working
- **Red/Yellow** -- Claude needs attention (permission prompt, question)

## Requirements

- macOS
- [Elgato Stream Deck Mini](https://www.elgato.com/stream-deck-mini) (6 keys)
- [Ghostty](https://ghostty.org/) terminal
- [uv](https://docs.astral.sh/uv/) for Python project management
- `hidapi` (`brew install hidapi`)
- Accessibility permissions for the terminal/app running SpookyCat

## Setup

```bash
# Install dependencies
brew install hidapi
uv sync

# Generate config (edit with your workspaces)
uv run python main.py
# First run creates ~/.config/lol.pjw.spookycat/spookycat.toml and exits

# Install Claude Code hooks (for state monitoring)
uv run python main.py install-hooks

# Install CLI helper (adds `spookycat` to ~/.local/bin)
uv run python main.py install-cli

# Install macOS app (for Raycast/Spotlight)
uv run python main.py install-app
```

## Usage

```bash
# Run from terminal
spookycat

# Run with debug logging
spookycat --log-level=debug

# Dynamically swap a workspace at runtime
spookycat set-workspace 5 ANO ~/telemetry-anomalies
```

Launch from Raycast by searching "SpookyCat". A menu bar icon (👻🐱) appears -- click it to quit.

### Button behavior

- **Tap** a button to switch to that Ghostty tab
- **Tap the active button** while the SpookyCat window is focused to switch back to your previous window (Cmd+\`)
- Unconfigured keys stay dark

## Config

Located at `~/.config/lol.pjw.spookycat/spookycat.toml`:

```toml
[settings]
poll_interval = 5

[colors]
inactive = "#000000"
working = "#2980b9"
done = "#27ae60"
asking = "#c0392b"

[[tabs]]
key = 0
icon = "α"
workspace = "~/projects/alpha"
init = ["echo 'ready'"]
```

### Tab fields

| Field | Description |
|-------|-------------|
| `key` | Stream Deck button (0-5), must be unique |
| `icon` | Displayed on button -- unicode char, emoji, or short string |
| `workspace` | Directory to `cd` into on tab creation |
| `init` | Commands to run after `cd` (optional) |

## Commands

| Command | Description |
|---------|-------------|
| `install-hooks` | Install Claude Code hooks for state monitoring |
| `uninstall-hooks` | Remove Claude Code hooks |
| `install-app` | Create SpookyCat.app in ~/Applications |
| `uninstall-app` | Remove SpookyCat.app |
| `install-cli` | Add `spookycat` to ~/.local/bin |
| `uninstall-cli` | Remove CLI helper |
| `print-sample-config` | Print example config to stdout |
| `set-workspace KEY ICON DIR` | Swap a workspace at runtime |

## How state monitoring works

SpookyCat monitors Claude Code via two mechanisms:

1. **Hooks** (push): Claude Code hooks in `~/.claude/settings.json` signal state changes through a Unix domain socket (`/tmp/spookycat.sock`). The hooks are no-ops when SpookyCat isn't running.

2. **Polling** (pull): Every `poll_interval` seconds, SpookyCat checks for `claude` processes via `pgrep`/`lsof` and reads git branches via `git rev-parse`. This catches cases where hooks don't fire (crash, manual exit).

## License

MIT
