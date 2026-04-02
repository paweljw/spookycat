import threading

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

from ghostty import GhosttyController

COLORS = ["#e74c3c", "#2ecc71", "#3498db", "#f39c12", "#9b59b6", "#1abc9c"]


def render_key_image(deck, text, bg_color="black", text_color="white"):
    image = Image.new("RGB", deck.key_image_format()["size"], bg_color)
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (image.width - text_w) // 2
    y = (image.height - text_h) // 2
    draw.text((x, y), text, font=font, fill=text_color)

    return image


def set_key(deck, key, text, bg_color="black"):
    image = render_key_image(deck, text, bg_color=bg_color)
    deck.set_key_image(key, PILHelper.to_native_format(deck, image))


def update_active_tab(deck, active_key):
    for key in range(deck.key_count()):
        if key == active_key:
            set_key(deck, key, f"T{key + 1}", bg_color=COLORS[key])
        else:
            set_key(deck, key, f"T{key + 1}")


def main():
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

    print("Setting up Ghostty...")
    ghostty = GhosttyController()

    update_active_tab(deck, 0)

    def on_key_change(deck, key, pressed):
        if not pressed:
            return
        print(f"Switching to tab {key + 1}")
        ghostty.switch_tab(key)
        update_active_tab(deck, key)

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
