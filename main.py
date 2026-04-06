import atexit
import logging
import signal
import threading
from pathlib import Path

from StreamDeck.DeviceManager import DeviceManager

from config import load_config
from deck import DECK_BRIGHTNESS, DeckController, show_splash
from ghostty import GhosttyController
from hooks import StateServer
from poller import Poller, check_claude_process, check_git_branch, invalidate_claude_cache

log = logging.getLogger("spookycat")


def handle_command(msg, ctrl, poller):
    cmd = msg.get("command")
    if cmd == "set-workspace":
        key = msg.get("key")
        icon = msg.get("icon", "?")
        workspace = Path(msg.get("workspace", "")).expanduser().resolve()
        ctrl.set_workspace(key, icon, workspace)
        poller.workspaces = [tab.workspace for tab in ctrl.config.tabs]
    else:
        log.warning("Unknown command: %s", cmd)


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

    deck.set_brightness(DECK_BRIGHTNESS)
    show_splash(deck)

    ctrl = DeckController(deck, config)

    def on_socket_event(msg):
        if "command" in msg:
            handle_command(msg, ctrl, poller)
        else:
            ctrl.on_hook_event(msg)

    server = StateServer(on_event=on_socket_event)
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

    ctrl._key_callback = on_key_change
    deck.set_key_callback(on_key_change)
    poller.pre_cycle_hooks.append(ctrl.try_reconnect)

    cleaned_up = threading.Event()

    def cleanup():
        if cleaned_up.is_set():
            return
        cleaned_up.set()
        poller.stop()
        server.stop()
        ghostty.close()
        if ctrl.connected:
            try:
                ctrl.deck.set_brightness(0)
                ctrl.deck.close()
            except Exception:
                log.debug("deck cleanup failed", exc_info=True)
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


if __name__ == "__main__":
    from cli import main

    main()
