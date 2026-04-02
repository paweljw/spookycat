import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from config import SpookyCatConfig, load_config, print_sample_config
from ghostty import GhosttyController
from hooks import StateServer, install_hooks, uninstall_hooks
from poller import Poller, check_claude_process, invalidate_claude_cache

SPLASH_PATH = Path(__file__).parent / "splash.png"
COLS, ROWS = 3, 2
SUBTITLE = "T-123456"

FONT_REGULAR = "/System/Library/Fonts/Helvetica.ttc"
FONT_BOLD_INDEX = 1


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
        sub_font = ImageFont.truetype(FONT_REGULAR, 10)
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
                print(f"  [state] key {key}: {old or 'inactive'} → {state}")
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
            image = render_key_image(
                self.deck,
                tab.icon,
                SUBTITLE,
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
            print(f"  [hook] {event} from {cwd} — no matching workspace")
            return
        print(f"  [hook] {event} → {workspace_str}")

        if event == "prompt_submit":
            self.update_claude_state(workspace_str, "working")
        elif event == "stop":
            self.update_claude_state(workspace_str, "done")
        elif event == "ask":
            self.update_claude_state(workspace_str, "asking")

    def on_poll_update(self, workspace, key, value):
        workspace_str = str(workspace)
        if key != "claude_running":
            return
        current = self.claude_states.get(workspace_str, "inactive")
        if value and current == "inactive":
            self.update_claude_state(workspace_str, "done")
        elif not value and current != "inactive":
            self.update_claude_state(workspace_str, "inactive")

    def _resolve_workspace(self, cwd_path):
        for tab in self.config.tabs:
            if cwd_path == tab.workspace or tab.workspace in cwd_path.parents:
                return str(tab.workspace)
        return None


def run():
    config = load_config()

    decks = DeviceManager().enumerate()
    print(f"Found {len(decks)} Stream Deck(s)")

    if not decks:
        print("No Stream Deck detected. Is it plugged in?")
        return

    deck = decks[0]
    deck.open()
    deck.reset()

    print(f"  Deck type:    {deck.deck_type()}")
    print(f"  Serial:       {deck.get_serial_number()}")
    print(f"  FW version:   {deck.get_firmware_version()}")
    print(f"  Key count:    {deck.key_count()}")

    deck.set_brightness(60)
    show_splash(deck)

    ctrl = DeckController(deck, config)

    server = StateServer(on_event=ctrl.on_hook_event)
    server.start()
    print("  Socket server listening")

    poller = Poller(
        interval=config.poll_interval,
        workspaces=[tab.workspace for tab in config.tabs],
        on_update=ctrl.on_poll_update,
    )
    poller.pre_cycle_hooks.append(invalidate_claude_cache)
    poller.register(check_claude_process)
    poller.start()
    print("  Poller started")

    print("Setting up Ghostty...")
    ghostty = GhosttyController(config.tabs)

    ctrl.ready = True
    ctrl._redraw()

    def on_key_change(deck, key, pressed):
        if not pressed or key not in ctrl.key_to_tab:
            return
        tab_index, _tab = ctrl.key_to_tab[key]
        print(f"Switching to tab {tab_index + 1} (key {key})")
        ghostty.switch_tab(tab_index)
        ctrl.set_active(key)

    deck.set_key_callback(on_key_change)

    print("\nSpookyCat ready! Ctrl+C to exit.")

    stop_event = threading.Event()
    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()
        server.stop()
        ghostty.close()
        deck.reset()
        deck.close()
        print("\nSpookyCat closed.")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "install-hooks":
            install_hooks()
        elif cmd == "uninstall-hooks":
            uninstall_hooks()
        elif cmd == "print-sample-config":
            print_sample_config()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: spookycat [install-hooks | uninstall-hooks | print-sample-config]")
            sys.exit(1)
        return

    run()


if __name__ == "__main__":
    main()
