"""
Badge and Popover windows built with AppKit (pyobjc).
These are non-activating NSPanels — they float above all windows
without stealing focus from the active app.
"""
import objc
from Foundation import NSObject, NSMakeRect
from objc import super as objc_super
from AppKit import (
    NSPanel,
    NSColor,
    NSButton,
    NSTextField,
    NSScrollView,
    NSTextView,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
    NSFont,
    NSBezelStyleRounded,
    NSLineBreakByWordWrapping,
    NSAttributedString,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
)

# NSWindowStyleMask constants (numeric to avoid import issues)
_BORDERLESS = 0
_NON_ACTIVATING = 1 << 7  # NSWindowStyleMaskNonactivatingPanel

# NSWindowCollectionBehavior
_JOIN_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4


# ---------------------------------------------------------------------------
# Generic button-click delegate
# ---------------------------------------------------------------------------

class _Handler(NSObject):
    def init(self):
        self = objc_super(_Handler, self).init()
        if self is None:
            return None
        self._cb = None
        return self

    def clicked_(self, sender):
        if self._cb:
            self._cb()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_panel(w: int, h: int, bg: NSColor) -> NSPanel:
    style = _BORDERLESS | _NON_ACTIVATING
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, w, h),
        style,
        NSBackingStoreBuffered,
        False,
    )
    panel.setLevel_(NSFloatingWindowLevel + 1)
    panel.setBackgroundColor_(bg)
    panel.setOpaque_(False)
    panel.setHasShadow_(True)
    panel.setCollectionBehavior_(_JOIN_ALL_SPACES | _STATIONARY)
    cv = panel.contentView()
    cv.setWantsLayer_(True)
    cv.layer().setCornerRadius_(8.0)
    cv.layer().setMasksToBounds_(True)
    return panel


def _label(text: str, frame, size: int, bold: bool = False, color: NSColor = None) -> NSTextField:
    tf = NSTextField.alloc().initWithFrame_(frame)
    tf.setStringValue_(text)
    tf.setEditable_(False)
    tf.setBordered_(False)
    tf.setDrawsBackground_(False)
    tf.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    tf.setTextColor_(color or NSColor.colorWithRed_green_blue_alpha_(0.80, 0.80, 0.88, 1.0))
    return tf


def _textbox(text: str, frame, highlight: bool = False) -> NSTextField:
    bg = (
        NSColor.colorWithRed_green_blue_alpha_(0.14, 0.24, 0.14, 1.0)
        if highlight
        else NSColor.colorWithRed_green_blue_alpha_(0.17, 0.17, 0.24, 1.0)
    )
    fg = (
        NSColor.colorWithRed_green_blue_alpha_(0.70, 0.96, 0.70, 1.0)
        if highlight
        else NSColor.colorWithRed_green_blue_alpha_(0.80, 0.80, 0.88, 1.0)
    )
    tf = NSTextField.alloc().initWithFrame_(frame)
    tf.setStringValue_(text)
    tf.setEditable_(False)
    tf.setBordered_(False)
    tf.setDrawsBackground_(True)
    tf.setBackgroundColor_(bg)
    tf.setFont_(NSFont.systemFontOfSize_(11))
    tf.setTextColor_(fg)
    tf.cell().setWraps_(True)
    tf.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
    return tf


def _attr_title(text: str, size: int = 13, color: NSColor = None) -> NSAttributedString:
    c = color or NSColor.whiteColor()
    return NSAttributedString.alloc().initWithString_attributes_(
        text,
        {
            NSForegroundColorAttributeName: c,
            NSFontAttributeName: NSFont.systemFontOfSize_(size),
        },
    )


def _btn(title: str, frame, handler: _Handler, bg: NSColor = None) -> NSButton:
    b = NSButton.alloc().initWithFrame_(frame)
    b.setTitle_(title)
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTarget_(handler)
    b.setAction_("clicked:")
    if bg:
        b.setWantsLayer_(True)
        b.layer().setBackgroundColor_(bg.CGColor())
        b.setBordered_(False)
        b.setAttributedTitle_(_attr_title(title))
    return b


# ---------------------------------------------------------------------------
# Badge
# ---------------------------------------------------------------------------

class BadgeWindow:
    W, H = 152, 30

    def __init__(self):
        self._panel: NSPanel | None = None
        self._handler = _Handler.alloc().init()
        self._visible = False

    def show(self, x: float, y: float, on_click):
        self._handler._cb = on_click
        if self._panel is None:
            self._panel = self._build()
        # Position just below and to the right of the cursor
        self._panel.setFrameOrigin_((x + 8, y - self.H - 6))
        self._panel.orderFront_(None)
        self._visible = True

    def hide(self):
        if self._panel and self._visible:
            self._panel.orderOut_(None)
            self._visible = False

    def _build(self) -> NSPanel:
        bg = NSColor.colorWithRed_green_blue_alpha_(0.10, 0.10, 0.16, 0.93)
        panel = _make_panel(self.W, self.H, bg)

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, self.W, self.H))
        btn.setBordered_(False)
        btn.setTarget_(self._handler)
        btn.setAction_("clicked:")
        accent = NSColor.colorWithRed_green_blue_alpha_(0.54, 0.71, 0.98, 1.0)
        btn.setAttributedTitle_(_attr_title("✦  Corrigir texto", size=12, color=accent))

        panel.contentView().addSubview_(btn)
        return panel


# ---------------------------------------------------------------------------
# Popover
# ---------------------------------------------------------------------------

class PopoverWindow:
    W, H = 390, 230

    def __init__(self):
        self._panel: NSPanel | None = None
        self._handlers: list[_Handler] = []

    def show(
        self,
        x: float,
        y: float,
        original: str,
        corrected: str,
        on_accept,
        on_cancel,
    ):
        self.hide()

        bg = NSColor.colorWithRed_green_blue_alpha_(0.11, 0.11, 0.17, 0.97)
        panel = _make_panel(self.W, self.H, bg)
        cv = panel.contentView()
        W, H = self.W, self.H

        # ── Title ──────────────────────────────────────────────────────────
        accent = NSColor.colorWithRed_green_blue_alpha_(0.54, 0.71, 0.98, 1.0)
        cv.addSubview_(_label("TextAssist — Sugestão", NSMakeRect(12, H - 28, W - 24, 18),
                               12, bold=True, color=accent))

        # ── Original ───────────────────────────────────────────────────────
        cv.addSubview_(_label("Original:", NSMakeRect(12, H - 48, 80, 14), 10))
        preview = original[:120] + ("…" if len(original) > 120 else "")
        cv.addSubview_(_textbox(preview, NSMakeRect(12, H - 90, W - 24, 38)))

        # ── Corrigido ──────────────────────────────────────────────────────
        cv.addSubview_(_label("Corrigido:", NSMakeRect(12, H - 108, 80, 14), 10))
        cv.addSubview_(_textbox(corrected, NSMakeRect(12, H - 158, W - 24, 46), highlight=True))

        # ── Buttons ────────────────────────────────────────────────────────
        accept_h = _Handler.alloc().init()
        accept_h._cb = lambda: (self.hide(), on_accept and on_accept())

        cancel_h = _Handler.alloc().init()
        cancel_h._cb = lambda: (self.hide(), on_cancel and on_cancel())

        copy_h = _Handler.alloc().init()
        copy_h._cb = lambda: self._copy(corrected)

        self._handlers = [accept_h, cancel_h, copy_h]

        green = NSColor.colorWithRed_green_blue_alpha_(0.20, 0.60, 0.30, 1.0)
        cv.addSubview_(_btn("Aceitar", NSMakeRect(12, 10, 88, 26), accept_h, bg=green))
        cv.addSubview_(_btn("Copiar", NSMakeRect(106, 10, 72, 26), copy_h))
        cv.addSubview_(_btn("Cancelar", NSMakeRect(184, 10, 72, 26), cancel_h))

        self._panel = panel
        self._panel.setFrameOrigin_((x + 8, y - self.H - 10))
        self._panel.orderFront_(None)

    def hide(self):
        if self._panel:
            self._panel.orderOut_(None)
            self._panel = None
            self._handlers.clear()

    def _copy(self, text: str):
        from AppKit import NSPasteboard, NSStringPboardType
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSStringPboardType)
