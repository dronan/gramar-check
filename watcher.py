"""
Background thread that monitors the focused text element for changes
and checks the current paragraph via LanguageTool (free).
"""
import threading
import time

_TEXT_ROLES = {
    "AXTextField", "AXTextArea",
    # Electron / Chrome / WhatsApp contentEditables
    "AXWebArea", "AXDocument", "AXGroup", "AXComboBox",
}
MAX_TEXT_LEN = 600   # LanguageTool free-tier limit
MIN_TEXT_LEN = 8
# If text changes by more than this in one poll tick, it's a focus/paste, not typing
_FOCUS_CHANGE_DELTA = 80


def _wake_chromium_accessibility(pid: int):
    """Apply AXManualAccessibility=True to force Electron/Chrome to expose text nodes."""
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementSetAttributeValue,
        )
        app_el = AXUIElementCreateApplication(pid)
        if app_el:
            AXUIElementSetAttributeValue(app_el, "AXManualAccessibility", True)
            print(f"[watcher] woke AX for pid={pid}")
    except Exception as e:
        print(f"[watcher] wake_chromium error: {e}")


def _focused_role() -> str | None:
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide,
            AXUIElementCopyAttributeValue,
            kAXFocusedUIElementAttribute,
            kAXRoleAttribute,
        )
        system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute, None)
        if err or focused is None:
            return None

        for _ in range(8):
            err2, inner = AXUIElementCopyAttributeValue(focused, kAXFocusedUIElementAttribute, None)
            if err2 or inner is None or inner == focused:
                break
            focused = inner

        err, role = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
        role_str = str(role) if (not err and role) else None

        # Chrome/Electron: kAXFocusedUIElement doesn't propagate through web
        # containers. Query the app element to get the actual focused node.
        _WEB_CONT = {"AXWebArea", "AXDocument", "AXGroup", "AXComboBox"}
        if role_str in _WEB_CONT:
            try:
                from ApplicationServices import AXUIElementCreateApplication
                from AppKit import NSWorkspace
                frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
                if frontmost:
                    app_el = AXUIElementCreateApplication(frontmost.processIdentifier())
                    err3, app_focused = AXUIElementCopyAttributeValue(
                        app_el, kAXFocusedUIElementAttribute, None
                    )
                    if not err3 and app_focused is not None:
                        err4, inner_role = AXUIElementCopyAttributeValue(
                            app_focused, kAXRoleAttribute, None
                        )
                        if not err4 and inner_role:
                            return str(inner_role)
            except Exception:
                pass

        return role_str
    except Exception:
        return None


def _current_paragraph(text: str, cursor: int) -> tuple[str, int]:
    """Returns (paragraph_text, start_offset) for the paragraph at `cursor`."""
    start = text.rfind("\n", 0, cursor)
    start = start + 1 if start >= 0 else 0
    end = text.find("\n", cursor)
    end = end if end >= 0 else len(text)
    return text[start:end], start


class TextWatcher:
    def __init__(self, on_errors_found, on_clear=None, debounce: float = 2.0):
        self._on_errors_found = on_errors_found
        self._on_clear = on_clear
        self._debounce = debounce
        self._last_text = ""
        self._last_checked = ""
        self._timer: threading.Timer | None = None
        self._running = False
        self._enabled = True
        self._prev_in_text = False
        self._last_pid: int | None = None

    def start(self):
        self._running = True
        threading.Thread(target=self._poll, daemon=True).start()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled and self._timer:
            self._timer.cancel()

    def mark_as_correct(self, text: str):
        self._last_checked = text
        self._last_text = text
        if self._timer:
            self._timer.cancel()

    # ------------------------------------------------------------------

    def _poll(self):
        import os
        from AppKit import NSWorkspace

        while self._running:
            if self._enabled:
                try:
                    # ── Protect against self-clearing when our own UI gets focus ──
                    frontmost = NSWorkspace.sharedWorkspace().frontmostApplication()
                    if frontmost and frontmost.processIdentifier() == os.getpid():
                        # The user is interacting with our CorrectionCard NSWindow.
                        # Do not clear the UI; just wait until they return to their text app.
                        time.sleep(0.5)
                        continue

                    from ax_monitor import get_focused_pid
                    current_pid = get_focused_pid()
                    if current_pid == os.getpid():
                        # Focus shifted to our non-activating panel / click view
                        time.sleep(0.5)
                        continue

                    # Wake Chromium/Electron accessibility when switching apps
                    if current_pid and current_pid != self._last_pid:
                        _wake_chromium_accessibility(current_pid)
                        self._last_pid = current_pid

                    role = _focused_role()
                    if role not in _TEXT_ROLES:
                        if self._prev_in_text and self._on_clear:
                            self._on_clear()
                        self._prev_in_text = False
                        if role:
                            print(f"[watcher] skipping role: {role}")
                    if role in _TEXT_ROLES:
                        self._prev_in_text = True
                        from ax_monitor import read_full_text
                        text = read_full_text() or ""

                        delta = abs(len(text) - len(self._last_text))

                        if delta >= _FOCUS_CHANGE_DELTA:
                            # Large jump = focus/paste/send, reset and clear UI
                            print(f"[watcher] focus/paste detected (delta={delta}), resetting")
                            self._last_text = text
                            self._last_checked = text
                            if self._timer:
                                self._timer.cancel()
                            if self._on_clear:
                                self._on_clear()

                        elif text != self._last_text and len(text.strip()) >= MIN_TEXT_LEN:
                            if len(text) <= MAX_TEXT_LEN:
                                print(f"[watcher] text changed ({len(self._last_text)}→{len(text)} chars), scheduling check")
                                self._last_text = text
                                if self._on_clear:
                                    self._on_clear()
                                self._schedule_check(text)
                            else:
                                self._last_text = text  # track but don't check

                except Exception as e:
                    print(f"[watcher] poll error: {e}")
            time.sleep(0.5)

    def _schedule_check(self, text: str):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce, self._run_check, args=[text])
        self._timer.daemon = True
        self._timer.start()

    def _run_check(self, text: str):
        if text != self._last_text:
            print("[watcher] text changed since timer, skipping")
            return
        if text == self._last_checked:
            print("[watcher] already checked this text, skipping")
            return
        self._last_checked = text

        try:
            from grammar_checker import check
            from ax_monitor import get_cursor_offset

            cursor = get_cursor_offset()
            if cursor is None:
                cursor = len(text)
            print(f"[watcher] cursor at {cursor}, text len {len(text)}")

            paragraph, para_start = _current_paragraph(text, cursor)
            print(f"[watcher] paragraph to check: {paragraph!r}")

            if len(paragraph.strip()) < MIN_TEXT_LEN:
                print("[watcher] paragraph too short, skipping")
                return

            errors = check(paragraph)
            print(f"[grammar] returned {len(errors)} error(s)")

            if errors:
                for e in errors:
                    e.offset += para_start
                    print(f"  → {e.original_word!r} at offset {e.offset}: {e.message}")
                self._on_errors_found(text, errors)

        except Exception as e:
            print(f"[watcher] check error: {e}")
