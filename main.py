"""
TextAssist — macOS menu bar app.
Monitors typed text system-wide using LanguageTool (free).
Shows inline highlights and sleek correction cards.
"""
import queue
import rumps

from ax_monitor import _check_permission, get_bounds_for_range, get_mouse_position, replace_full_text
from watcher import TextWatcher
from overlay import OverlayManager
from correction_card import CorrectionCard

_ui_queue: queue.Queue = queue.Queue()


def _schedule(fn):
    """Thread-safe: enqueue a UI task to run on the main thread via rumps timer."""
    _ui_queue.put(fn)


class TextAssistApp(rumps.App):
    def __init__(self):
        super().__init__("✦", icon=None, quit_button="Quit")
        self.menu = [
            rumps.MenuItem("Ativo", callback=self._toggle),
            rumps.separator,
            rumps.MenuItem("Verificar Acessibilidade", callback=self._check_ax),
        ]
        self._enabled = True
        self._current_text = ""

        # UI components — keep strong refs so AppKit doesn't GC them
        self._overlay = OverlayManager()
        self._card = CorrectionCard()

        # Background text watcher (uses LanguageTool, not OpenAI)
        self._watcher = TextWatcher(
            on_errors_found=self._on_errors_found,
            on_clear=lambda: _schedule(self._clear_ui),
            debounce=2.0,
        )
        self._watcher.start()

        # Drain the UI queue on the main thread every 200 ms
        self._queue_timer = rumps.Timer(self._process_queue, 0.2)
        self._queue_timer.start()

    # ------------------------------------------------------------------
    # Queue drain (runs on main thread)
    # ------------------------------------------------------------------

    def _process_queue(self, _sender):
        while not _ui_queue.empty():
            try:
                _ui_queue.get_nowait()()
            except Exception as e:
                print(f"[main] {e}")

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _toggle(self, sender):
        self._enabled = not self._enabled
        sender.title = "Ativo" if self._enabled else "Pausado"
        self.title = "✦" if self._enabled else "✦⏸"
        self._watcher.set_enabled(self._enabled)
        if not self._enabled:
            self._clear_ui()

    def _check_ax(self, _sender):
        ok = _check_permission()
        rumps.alert(
            title="Permissão de Acessibilidade",
            message="Permissão concedida." if ok else
                    "Permissão NÃO concedida.\n"
                    "O System Settings foi aberto — adicione este app em Accessibility.",
        )

    # ------------------------------------------------------------------
    # Watcher callbacks (called from background thread → scheduled on main)
    # ------------------------------------------------------------------

    def _on_errors_found(self, text: str, errors: list):
        _schedule(lambda: self._show_highlights(text, errors))

    # ------------------------------------------------------------------
    # UI logic (always runs on main thread via queue)
    # ------------------------------------------------------------------

    def _clear_ui(self):
        self._card.hide()
        self._overlay.clear()

    def _show_highlights(self, text: str, errors: list):
        self._current_text = text
        self._card.hide()

        # Capture mouse position at the moment errors are found.
        # Used as fallback for apps where AX bounds are unavailable (browsers, etc).
        mouse_pos = get_mouse_position()

        def get_bounds(offset, length):
            return get_bounds_for_range(offset, length)

        # Split errors: spelling gets red per-word underlines,
        # grammar/style gets a single yellow underline spanning the phrase.
        spelling = [e for e in errors if e.category == "Spelling"]
        grammar  = [e for e in errors if e.category != "Spelling"]

        def on_spelling_click(error, bounds):
            x, y = bounds[0], bounds[1]
            remaining = [e for e in errors if e is not error]
            self._card.show_single(
                x, y, error,
                on_accept=lambda e: self._accept(text, e, remaining),
                # Dismiss only hides the card — other underlines stay alive.
                on_dismiss=self._card.hide,
            )

        def on_grammar_click(bounds):
            x, y = bounds[0], bounds[1]
            # Pass ALL errors so the card shows every correction (spelling + grammar)
            self._card.show_all(
                x, y, errors, original_text=text,
                on_accept_one=lambda e: self._accept(text, e, [r for r in errors if r is not e]),
                on_accept_all=lambda: self._accept_all(text, errors),
                on_dismiss=self._clear_ui,
            )

        any_shown = self._overlay.show_errors(
            spelling, grammar, get_bounds, on_spelling_click, on_grammar_click,
        )

        if any_shown:
            self._overlay.start_tracking()

        # Browser/Electron fallback: show full diff card at cursor.
        if not any_shown and errors and mouse_pos:
            mx, my = mouse_pos
            self._card.show_all(
                mx, my, errors, original_text=text,
                on_accept_one=lambda e: self._accept(text, e, [r for r in errors if r is not e]),
                on_accept_all=lambda: self._accept_all(text, errors),
                on_dismiss=self._clear_ui,
            )

    def _accept(self, original_text: str, error, remaining_errors: list = None):
        """Apply a single error's replacement; keep overlays for remaining errors."""
        if not error.replacements:
            return
        replacement = error.replacements[0]
        offset_delta = len(replacement) - error.length
        corrected = (
            original_text[: error.offset]
            + replacement
            + original_text[error.offset + error.length :]
        )
        replace_full_text(corrected)

        if remaining_errors:
            # Shift offsets of errors that follow the fixed one.
            for e in remaining_errors:
                if e.offset > error.offset:
                    e.offset += offset_delta
            self._watcher.mark_as_correct(corrected)
            self._card.hide()
            self._overlay.clear()
            self._show_highlights(corrected, remaining_errors)
        else:
            self._watcher.mark_as_correct(corrected)
            self._clear_ui()

    def _accept_all(self, original_text: str, errors: list):
        """Apply all errors' first replacements at once, in reverse offset order."""
        # Process in reverse so earlier offsets aren't shifted by later replacements.
        corrected = original_text
        for error in sorted(errors, key=lambda e: e.offset, reverse=True):
            if not error.replacements:
                continue
            replacement = error.replacements[0]
            corrected = (
                corrected[: error.offset]
                + replacement
                + corrected[error.offset + error.length :]
            )
        replace_full_text(corrected)
        self._watcher.mark_as_correct(corrected)
        self._clear_ui()

    # ------------------------------------------------------------------

    def run(self):
        if not _check_permission():
            rumps.alert(
                title="TextAssist — Permissão necessária",
                message="Adicione este terminal/app em:\n"
                        "System Settings → Privacy & Security → Accessibility",
            )
        super().run()


if __name__ == "__main__":
    TextAssistApp().run()
