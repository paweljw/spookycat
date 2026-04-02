import atexit
import logging
import shutil
import signal
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from config import SpookyCatConfig, load_config, print_sample_config
from ghostty import GhosttyController
from hooks import StateServer, install_hooks, uninstall_hooks
from poller import Poller, check_claude_process, check_git_branch, invalidate_claude_cache

log = logging.getLogger("spookycat")

SPLASH_PATH = Path(__file__).parent / "splash.png"
COLS, ROWS = 3, 2

FONT_REGULAR = "/System/Library/Fonts/Helvetica.ttc"
FONT_BOLD_INDEX = 1

APP_DIR = Path.home() / "Applications" / "SpookyCat.app"


def show_splash(deck):
    key_w, key_h = deck.key_image_format()["size"]
    canvas_w, canvas_h = key_w * COLS, key_h * ROWS
    splash = Image.open(SPLASH_PATH).convert("RGB")
    splash = splash.resize((canvas_w, canvas_h), Image.LANCZOS)

    for key in range(deck.key_count()):
        col = key % COLS
        row = key // COLS
        tile = splash.crop((col * key_w, row * key_h, (col + 1) * key_w, (row + 1) * key_h))
        deck.set_key_image(key, PILHelper.to_native_format(deck, tile))


def render_key_image(deck, icon, subtitle="", bg_color="black", text_color="white", bold=False):
    image = Image.new("RGB", deck.key_image_format()["size"], bg_color)
    draw = ImageDraw.Draw(image)

    try:
        icon_font = ImageFont.truetype(FONT_REGULAR, 24, index=FONT_BOLD_INDEX if bold else 0)
        sub_font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 11)
    except OSError:
        icon_font = ImageFont.load_default()
        sub_font = icon_font

    bbox = draw.textbbox((0, 0), icon, font=icon_font)
    icon_w = bbox[2] - bbox[0]
    draw.text(((image.width - icon_w) // 2, 14), icon, font=icon_font, fill=text_color)

    if subtitle:
        bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sub_w = bbox[2] - bbox[0]
        draw.text(((image.width - sub_w) // 2, 52), subtitle, font=sub_font, fill=text_color)

    return image


class DeckController:
    def __init__(self, deck, config: SpookyCatConfig):
        self.deck = deck
        self.config = config
        self.key_to_tab = {tab.key: (i, tab) for i, tab in enumerate(config.tabs)}
        self.ws_to_key = {str(tab.workspace): tab.key for tab in config.tabs}
        self.active_key = config.tabs[0].key
        self.claude_states = {}
        self.subtitles = {}
        self.ready = False
        self._lock = threading.Lock()

    def set_active(self, key):
        with self._lock:
            self.active_key = key
            self._redraw()

    def update_claude_state(self, workspace_str, state):
        with self._lock:
            old = self.claude_states.get(workspace_str)
            if old != state:
                self.claude_states[workspace_str] = state
                key = self.ws_to_key.get(workspace_str, "?")
                log.debug("key %s: %s → %s", key, old or "inactive", state)
                if self.ready:
                    self._redraw()

    def _bg_color(self, key):
        _idx, tab = self.key_to_tab[key]
        state = self.claude_states.get(str(tab.workspace), "inactive")
        return getattr(self.config.colors, state)

    def _redraw(self):
        fmt = self.deck.key_image_format()
        for key in range(self.deck.key_count()):
            if key not in self.key_to_tab:
                blank = Image.new("RGB", fmt["size"], "black")
                self.deck.set_key_image(key, PILHelper.to_native_format(self.deck, blank))
                continue
            _idx, tab = self.key_to_tab[key]
            subtitle = self.subtitles.get(str(tab.workspace), "")
            image = render_key_image(
                self.deck,
                tab.icon,
                subtitle,
                bg_color=self._bg_color(key),
                bold=(key == self.active_key),
            )
            self.deck.set_key_image(key, PILHelper.to_native_format(self.deck, image))

    def on_hook_event(self, msg):
        cwd = msg.get("cwd", "")
        event = msg.get("event", "")
        cwd_path = Path(cwd).resolve()

        workspace_str = self._resolve_workspace(cwd_path)
        if not workspace_str:
            log.debug("hook %s from %s — no matching workspace", event, cwd)
            return
        log.debug("hook %s → %s", event, workspace_str)

        if event == "prompt_submit":
            self.update_claude_state(workspace_str, "working")
        elif event == "stop":
            self.update_claude_state(workspace_str, "done")
        elif event == "ask":
            self.update_claude_state(workspace_str, "asking")

    def on_poll_update(self, workspace, key, value):
        workspace_str = str(workspace)
        if key == "claude_running":
            current = self.claude_states.get(workspace_str, "inactive")
            if value and current == "inactive":
                self.update_claude_state(workspace_str, "done")
            elif not value and current != "inactive":
                self.update_claude_state(workspace_str, "inactive")
        elif key == "git_subtitle":
            with self._lock:
                old = self.subtitles.get(workspace_str)
                if old != value:
                    self.subtitles[workspace_str] = value
                    log.debug(
                        "subtitle %s: %s",
                        self.ws_to_key.get(workspace_str, "?"),
                        value,
                    )
                    if self.ready:
                        self._redraw()

    def _resolve_workspace(self, cwd_path):
        for tab in self.config.tabs:
            if cwd_path == tab.workspace or tab.workspace in cwd_path.parents:
                return str(tab.workspace)
        return None


def run(log_level):
    import rumps

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config()

    decks = DeviceManager().enumerate()
    log.info("Found %d Stream Deck(s)", len(decks))

    if not decks:
        log.error("No Stream Deck detected. Is it plugged in?")
        return

    deck = decks[0]
    deck.open()
    deck.reset()

    log.info(
        "Deck: %s  Serial: %s  Keys: %d",
        deck.deck_type(),
        deck.get_serial_number(),
        deck.key_count(),
    )

    deck.set_brightness(60)
    show_splash(deck)

    ctrl = DeckController(deck, config)

    server = StateServer(on_event=ctrl.on_hook_event)
    server.start()
    log.info("Socket server listening")

    poller = Poller(
        interval=config.poll_interval,
        workspaces=[tab.workspace for tab in config.tabs],
        on_update=ctrl.on_poll_update,
    )
    poller.pre_cycle_hooks.append(invalidate_claude_cache)
    poller.register(check_claude_process)
    poller.register(check_git_branch)
    poller.start()
    log.info("Poller started (interval: %ds)", config.poll_interval)

    log.info("Setting up Ghostty...")
    ghostty = GhosttyController(config.tabs)

    ctrl.ready = True
    ctrl._redraw()

    def on_key_change(deck, key, pressed):
        if not pressed or key not in ctrl.key_to_tab:
            return
        tab_index, _tab = ctrl.key_to_tab[key]
        if key == ctrl.active_key and ghostty.is_focused():
            log.info("Switching away from SpookyCat window (key %d)", key)
            ghostty.switch_away()
        else:
            log.info("Switching to tab %d (key %d)", tab_index + 1, key)
            ghostty.switch_tab(tab_index)
            ctrl.set_active(key)

    deck.set_key_callback(on_key_change)

    cleaned_up = threading.Event()

    def cleanup():
        if cleaned_up.is_set():
            return
        cleaned_up.set()
        poller.stop()
        server.stop()
        ghostty.close()
        deck.reset()
        deck.close()
        log.info("SpookyCat closed.")

    atexit.register(cleanup)

    class SpookyCatMenuBar(rumps.App):
        def __init__(self):
            super().__init__("👻🐱", quit_button=None)
            self.menu = [rumps.MenuItem("Quit SpookyCat", callback=self._quit)]

        def _quit(self, _):
            cleanup()
            rumps.quit_application()

    app = SpookyCatMenuBar()

    def sigint_handler(sig, frame):
        cleanup()
        rumps.quit_application()

    signal.signal(signal.SIGINT, sigint_handler)

    log.info("SpookyCat ready!")
    app.run()


def install_app():
    project_dir = Path(__file__).parent.resolve()
    uv_path = shutil.which("uv")
    if not uv_path:
        print("Error: uv not found in PATH")
        sys.exit(1)

    contents = APP_DIR / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    exe = macos / "SpookyCat"
    exe.write_text(f'#!/bin/bash\ncd "{project_dir}"\nexec "{uv_path}" run python main.py\n')
    exe.chmod(0o755)

    plist = contents / "Info.plist"
    plist.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>SpookyCat</string>
    <key>CFBundleIdentifier</key>
    <string>lol.pjw.spookycat</string>
    <key>CFBundleName</key>
    <string>SpookyCat</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
""")

    print(f"Installed to {APP_DIR}")
    print("Launch from Raycast/Spotlight — look for 'SpookyCat'.")


def uninstall_app():
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
        print(f"Removed {APP_DIR}")
    else:
        print("SpookyCat.app not found in ~/Applications.")


def main():
    log_level = "info"
    args = sys.argv[1:]

    filtered = []
    for arg in args:
        if arg.startswith("--log-level="):
            log_level = arg.split("=", 1)[1]
        else:
            filtered.append(arg)

    if filtered:
        cmd = filtered[0]
        commands = {
            "install-hooks": install_hooks,
            "uninstall-hooks": uninstall_hooks,
            "install-app": install_app,
            "uninstall-app": uninstall_app,
            "print-sample-config": print_sample_config,
        }
        if cmd in commands:
            commands[cmd]()
        else:
            print(f"Unknown command: {cmd}")
            print("Commands: install-hooks, uninstall-hooks, install-app,")
            print("         uninstall-app, print-sample-config")
            sys.exit(1)
        return

    run(log_level)


if __name__ == "__main__":
    main()
