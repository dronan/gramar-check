"""
Floating popover window (non-activating) built with tkinter.
Displays action buttons and the AI result without stealing focus.
"""
import tkinter as tk
import threading
from typing import Callable


ACTIONS = [
    ("Corrigir", "fix"),
    ("Traduzir", "translate"),
    ("Reescrever", "rewrite"),
    ("Completar", "complete"),
]

BG = "#1e1e2e"
FG = "#cdd6f4"
BTN_BG = "#313244"
BTN_ACTIVE = "#45475a"
ACCENT = "#89b4fa"
FONT = ("SF Pro Text", 13)
FONT_SMALL = ("SF Pro Text", 11)


def _get_mouse_position() -> tuple[int, int]:
    try:
        from AppKit import NSEvent
        loc = NSEvent.mouseLocation()
        import Quartz
        screen_h = Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID())
        return int(loc.x), int(screen_h - loc.y)
    except Exception:
        return 100, 100


class Popover:
    def __init__(self, selected_text: str, on_action: Callable[[str, str], None]):
        self._selected_text = selected_text
        self._on_action = on_action
        self._root: tk.Tk | None = None
        self._result_var: tk.StringVar | None = None
        self._status_var: tk.StringVar | None = None
        self._result_text: str = ""

    def show(self):
        """Must be called from the main thread."""
        x, y = _get_mouse_position()

        root = tk.Tk()
        self._root = root
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.97)
        root.configure(bg=BG)

        # Position near cursor, offset slightly
        root.geometry(f"+{x + 12}+{y + 12}")

        self._result_var = tk.StringVar(value="")
        self._status_var = tk.StringVar(value="Escolha uma ação:")

        self._build_ui(root)

        # Close when focus is lost
        root.bind("<FocusOut>", lambda e: self._close())
        root.bind("<Escape>", lambda e: self._close())

        root.mainloop()

    def _build_ui(self, root: tk.Tk):
        pad = {"padx": 10, "pady": 6}

        # Header
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", **pad)
        tk.Label(header, text="TextAssist", bg=BG, fg=ACCENT, font=(FONT[0], 12, "bold")).pack(side="left")
        tk.Button(
            header, text="✕", bg=BG, fg=FG, bd=0, cursor="hand2",
            activebackground=BTN_ACTIVE, font=FONT_SMALL,
            command=self._close,
        ).pack(side="right")

        # Selected text preview
        preview = self._selected_text[:80] + ("…" if len(self._selected_text) > 80 else "")
        tk.Label(root, text=preview, bg=BTN_BG, fg=FG, font=FONT_SMALL,
                 wraplength=320, justify="left", anchor="w",
                 padx=8, pady=4).pack(fill="x", padx=10, pady=(0, 6))

        # Status label
        tk.Label(root, textvariable=self._status_var, bg=BG, fg=FG,
                 font=FONT_SMALL).pack(anchor="w", padx=10)

        # Action buttons
        btn_frame = tk.Frame(root, bg=BG)
        btn_frame.pack(fill="x", padx=10, pady=4)
        for label, action in ACTIONS:
            tk.Button(
                btn_frame, text=label, bg=BTN_BG, fg=FG, bd=0,
                activebackground=BTN_ACTIVE, activeforeground=FG,
                font=FONT, padx=10, pady=4, cursor="hand2",
                command=lambda a=action: self._trigger_action(a),
            ).pack(side="left", padx=2)

        # Result area (hidden until an action runs)
        self._result_frame = tk.Frame(root, bg=BG)
        self._result_text_widget = tk.Text(
            self._result_frame, bg=BTN_BG, fg=FG, font=FONT_SMALL,
            wrap="word", width=40, height=5, bd=0, padx=6, pady=4,
        )
        self._result_text_widget.pack(fill="both", expand=True)

        # Accept / Cancel
        action_frame = tk.Frame(self._result_frame, bg=BG)
        action_frame.pack(fill="x", pady=(4, 0))
        tk.Button(
            action_frame, text="Aceitar", bg=ACCENT, fg=BG, bd=0,
            font=(FONT[0], 12, "bold"), padx=12, pady=4, cursor="hand2",
            command=self._accept,
        ).pack(side="left", padx=2)
        tk.Button(
            action_frame, text="Cancelar", bg=BTN_BG, fg=FG, bd=0,
            font=FONT_SMALL, padx=10, pady=4, cursor="hand2",
            command=self._close,
        ).pack(side="left", padx=2)

    def _trigger_action(self, action: str):
        self._status_var.set("Processando…")
        self._result_frame.pack_forget()

        def run():
            try:
                result = self._on_action(action, self._selected_text)
                self._result_text = result
                self._root.after(0, self._show_result, result)
            except Exception as exc:
                self._root.after(0, self._show_error, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _show_result(self, text: str):
        self._status_var.set("Resultado:")
        self._result_text_widget.config(state="normal")
        self._result_text_widget.delete("1.0", "end")
        self._result_text_widget.insert("1.0", text)
        self._result_text_widget.config(state="disabled")
        self._result_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _show_error(self, msg: str):
        self._status_var.set(f"Erro: {msg}")

    def _accept(self):
        if self._result_text:
            from ax_monitor import replace_selected_text
            replace_selected_text(self._result_text)
        self._close()

    def _close(self):
        if self._root:
            self._root.destroy()
            self._root = None
