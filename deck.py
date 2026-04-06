import logging
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from config import SpookyCatConfig, TabConfig

log = logging.getLogger("spookycat")

SPLASH_PATH = Path(__file__).parent / "splash.png"
# Stream Deck Mini physical layout
COLS, ROWS = 3, 2

FONT_REGULAR = "/System/Library/Fonts/Helvetica.ttc"
FONT_BOLD_INDEX = 1
DECK_BRIGHTNESS = 60
# Vertical offsets for icon/subtitle text on 72x72 key images
ICON_Y = 14
SUBTITLE_Y = 52


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
    draw.text(((image.width - icon_w) // 2, ICON_Y), icon, font=icon_font, fill=text_color)

    if subtitle:
        bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
        sub_w = bbox[2] - bbox[0]
        x = (image.width - sub_w) // 2
        draw.text((x, SUBTITLE_Y), subtitle, font=sub_font, fill=text_color)

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
        self.connected = True
        self._key_callback = None
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

    def _deck_op(self, fn):
        try:
            fn()
            if not self.connected:
                self.connected = True
                log.info("Stream Deck reconnected")
        except Exception:
            if self.connected:
                self.connected = False
                log.warning("Stream Deck disconnected")

    def _redraw(self):
        if not self.connected:
            return
        for key in range(self.deck.key_count()):
            if key not in self.key_to_tab:
                blank = Image.new("RGB", self.deck.key_image_format()["size"], "black")
                self._deck_op(
                    lambda k=key, b=blank: self.deck.set_key_image(
                        k, PILHelper.to_native_format(self.deck, b)
                    )
                )
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
            self._deck_op(
                lambda k=key, img=image: self.deck.set_key_image(
                    k, PILHelper.to_native_format(self.deck, img)
                )
            )

    def try_reconnect(self):
        if self.connected:
            try:
                self.deck.get_serial_number()
                return
            except Exception:
                self.connected = False
                log.warning("Stream Deck disconnected")
        decks = DeviceManager().enumerate()
        if not decks:
            return
        try:
            self.deck = decks[0]
            self.deck.open()
            self.deck.set_brightness(DECK_BRIGHTNESS)
            self.connected = True
            log.info("Stream Deck reconnected")
            self._redraw()
            self.deck.set_key_callback(self._key_callback)
        except Exception:
            log.debug("Stream Deck reconnect failed", exc_info=True)

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

    def set_workspace(self, key, icon, workspace):
        with self._lock:
            if key not in self.key_to_tab:
                log.warning("set-workspace: key %d not configured", key)
                return
            idx, old_tab = self.key_to_tab[key]
            old_ws = str(old_tab.workspace)

            del self.ws_to_key[old_ws]
            self.claude_states.pop(old_ws, None)
            self.subtitles.pop(old_ws, None)

            new_tab = TabConfig(key=key, icon=icon, workspace=workspace, init=[])
            self.config.tabs[idx] = new_tab
            self.key_to_tab[key] = (idx, new_tab)
            self.ws_to_key[str(workspace)] = key

            log.info("key %d: %s → %s (%s)", key, old_tab.icon, icon, workspace)
            if self.ready:
                self._redraw()

    def _resolve_workspace(self, cwd_path):
        for tab in self.config.tabs:
            if cwd_path == tab.workspace or tab.workspace in cwd_path.parents:
                return str(tab.workspace)
        return None
