import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from config import load_config
from ghostty import GhosttyController

COLORS = ["#e74c3c", "#2ecc71", "#3498db", "#f39c12", "#9b59b6", "#1abc9c"]
SUBTITLE = "T-123456"
SPLASH_PATH = Path(__file__).parent / "splash.png"
COLS, ROWS = 3, 2


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


def render_key_image(deck, icon, subtitle="", bg_color="black", text_color="white"):
    image = Image.new("RGB", deck.key_image_format()["size"], bg_color)
    draw = ImageDraw.Draw(image)

    try:
        icon_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
        sub_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 10)
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


def main():
    tabs = load_config()
    key_to_tab = {tab.key: (i, tab) for i, tab in enumerate(tabs)}

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

    print("Setting up Ghostty...")
    ghostty = GhosttyController(tabs)

    def update_buttons(active_key):
        for key in range(deck.key_count()):
            if key not in key_to_tab:
                blank = Image.new("RGB", deck.key_image_format()["size"], "black")
                deck.set_key_image(key, PILHelper.to_native_format(deck, blank))
                continue
            _idx, tab = key_to_tab[key]
            bg = COLORS[key % len(COLORS)] if key == active_key else "black"
            image = render_key_image(deck, tab.icon, SUBTITLE, bg_color=bg)
            deck.set_key_image(key, PILHelper.to_native_format(deck, image))

    update_buttons(tabs[0].key)

    def on_key_change(deck, key, pressed):
        if not pressed or key not in key_to_tab:
            return
        tab_index, _tab = key_to_tab[key]
        print(f"Switching to tab {tab_index + 1} (key {key})")
        ghostty.switch_tab(tab_index)
        update_buttons(key)

    deck.set_key_callback(on_key_change)

    print("\nSpookyCat ready! Press buttons to switch tabs. Ctrl+C to exit.")

    stop_event = threading.Event()
    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        ghostty.close()
        deck.reset()
        deck.close()
        print("\nSpookyCat closed.")


if __name__ == "__main__":
    main()
