"""
Global hotkey listener using pynput.
Runs in a background daemon thread.
"""
import threading
from pynput import keyboard


def _parse_hotkey(hotkey_str: str):
    """Converts '<alt>+<space>' style string into a pynput HotKey combination."""
    parts = hotkey_str.split("+")
    keys = set()
    for part in parts:
        part = part.strip()
        if part.startswith("<") and part.endswith(">"):
            name = part[1:-1]
            keys.add(getattr(keyboard.Key, name, None))
        else:
            keys.add(keyboard.KeyCode.from_char(part))
    return frozenset(k for k in keys if k is not None)


class HotkeyListener:
    def __init__(self, hotkey: str, callback):
        self._combo = _parse_hotkey(hotkey)
        self._callback = callback
        self._pressed: set = set()
        self._listener: keyboard.Listener | None = None

    def _on_press(self, key):
        self._pressed.add(key)
        if self._combo.issubset(self._pressed):
            self._pressed.clear()
            try:
                self._callback()
            except Exception as exc:
                print(f"[hotkey] callback error: {exc}")

    def _on_release(self, key):
        self._pressed.discard(key)

    def start(self):
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        thread = threading.Thread(target=self._listener.start, daemon=True)
        thread.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
