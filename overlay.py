"""
Highlight panels drawn over grammar errors using AppKit NSPanel.
Each error word gets its own non-activating transparent panel with a
red squiggly underline. A summary badge shows the total issue count.
"""
import math
import threading
import time
import objc
from objc import super as objc_super
from Foundation import NSMakeRect, NSMakePoint, NSAttributedString, NSObject
from AppKit import (
    NSPanel,
    NSView,
    NSColor,
    NSBezierPath,
    NSFont,
    NSBackingStoreBuffered,
    NSNormalWindowLevel,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
)

_BORDERLESS = 0
_NON_ACTIVATING = 1 << 7
_JOIN_ALL_SPACES = 1 << 0
_STATIONARY = 1 << 4
_UNDERLINE_H = 5

# Underline colors
_RED    = (0.88, 0.15, 0.15, 0.95)   # spelling errors
_YELLOW = (0.85, 0.60, 0.05, 0.95)   # grammar / style errors


def _make_base_panel(x, y, w, h):
    style = _BORDERLESS | _NON_ACTIVATING
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, w, h), style, NSBackingStoreBuffered, False,
    )
    panel.setLevel_(NSNormalWindowLevel + 2)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setOpaque_(False)
    panel.setHasShadow_(False)
    panel.setIgnoresMouseEvents_(False)
    panel.setCollectionBehavior_(_JOIN_ALL_SPACES | _STATIONARY)
    return panel


# ---------------------------------------------------------------------------
# Squiggly underline
# ---------------------------------------------------------------------------

class _HighlightView(NSView):
    def initWithFrame_(self, frame):
        self = objc_super(_HighlightView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = None
        self._color = _RED
        return self

    def drawRect_(self, dirty_rect):
        w = self.frame().size.width
        r, g, b, a = self._color
        NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).setStroke()
        path = NSBezierPath.bezierPath()
        path.setLineWidth_(1.5)
        x, first = 0.0, True
        while x < w:
            y = 1.5 + 1.2 * math.sin(x * math.pi * 2.0 / 5.0)
            if first:
                path.moveToPoint_(NSMakePoint(x, y)); first = False
            else:
                path.lineToPoint_(NSMakePoint(x, y))
            x += 0.8
        path.stroke()

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()

    def acceptsFirstMouse_(self, event):
        return True


class _HighlightPanel:
    def __init__(self, bounds, on_click, color=_RED):
        x, y, w, h = bounds
        ul_w = max(w, 12)
        panel = _make_base_panel(x, y - _UNDERLINE_H + 1, ul_w, _UNDERLINE_H)
        view = _HighlightView.alloc().initWithFrame_(NSMakeRect(0, 0, ul_w, _UNDERLINE_H))
        view._on_click = on_click
        view._color = color
        panel.setContentView_(view)
        panel.orderFront_(None)
        self._panel = panel

    def reposition(self, bounds):
        x, y, w, h = bounds
        ul_w = max(w, 12)
        self._panel.setFrame_display_(
            NSMakeRect(x, y - _UNDERLINE_H + 1, ul_w, _UNDERLINE_H), True
        )

    def hide(self):
        self._panel.orderOut_(None)


# ---------------------------------------------------------------------------
# Summary badge  "✦ 2 issues"
# ---------------------------------------------------------------------------

class _BadgeView(NSView):
    def initWithFrame_(self, frame):
        self = objc_super(_BadgeView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = None
        self._label = ""
        return self

    def drawRect_(self, dirty_rect):
        w = self.frame().size.width
        h = self.frame().size.height
        # Pill background
        r, g, b, a = getattr(self, '_bg_color', (0.80, 0.12, 0.12, 0.90))
        NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, w, h), h / 2, h / 2
        ).fill()
        # Label
        attrs = {
            NSForegroundColorAttributeName: NSColor.whiteColor(),
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(10),
        }
        ns = NSAttributedString.alloc().initWithString_attributes_(self._label, attrs)
        sz = ns.size()
        ns.drawAtPoint_(NSMakePoint((w - sz.width) / 2, (h - sz.height) / 2))

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()

    def acceptsFirstMouse_(self, event):
        return True


class _SummaryBadge:
    W, H = 94, 20
    _RED    = (0.80, 0.12, 0.12, 0.90)
    _AMBER  = (0.75, 0.50, 0.02, 0.95)

    def __init__(self, x, y, count: int, on_click, color=None):
        panel = _make_base_panel(x, y + 4, self.W, self.H)
        panel.setHasShadow_(True)
        view = _BadgeView.alloc().initWithFrame_(NSMakeRect(0, 0, self.W, self.H))
        view._label = f"✦  {count} issue{'s' if count > 1 else ''}"
        view._bg_color = color or self._RED
        view._on_click = on_click
        panel.setContentView_(view)
        panel.orderFront_(None)
        self._panel = panel

    def hide(self):
        self._panel.orderOut_(None)


# ---------------------------------------------------------------------------
# Main-thread dispatcher (performSelectorOnMainThread target)
# ---------------------------------------------------------------------------

class _MainThreadDispatcher(NSObject):
    def init(self):
        self = objc_super(_MainThreadDispatcher, self).init()
        self._manager = None
        return self

    def hide_(self, _):
        if self._manager is not None:
            self._manager._clear_panels()

    def rebuild_(self, _):
        if self._manager is not None:
            self._manager._rebuild()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class OverlayManager:
    def __init__(self):
        self._panels: list = []
        self._spelling_errors = []
        self._all_errors = []
        self._get_bounds_fn = None
        self._on_grammar_click = None
        self._on_spelling_click = None
        self._anchor_error = None
        self._anchor_bounds = None
        self._tracking_active = False
        self._tracking_thread = None
        self._dispatcher = None

    def show_errors(self, spelling_errors, grammar_errors, get_bounds_fn,
                    on_spelling_click_fn, on_grammar_click_fn) -> bool:
        """
        Correction overlay:
          • Red squiggly per spelling word → on_spelling_click_fn(error, bounds)
          • ONE amber underline spanning ALL errors (spelling + grammar) → on_grammar_click_fn
            This yellow span always appears whenever there are any issues, regardless of
            whether the errors are Spelling or Grammar category.
        Returns True if at least one overlay was placed.
        """
        self._spelling_errors = spelling_errors
        self._all_errors = spelling_errors + grammar_errors
        self._get_bounds_fn = get_bounds_fn
        self._on_spelling_click = on_spelling_click_fn
        self._on_grammar_click = on_grammar_click_fn
        return self._rebuild()

    def _rebuild(self) -> bool:
        self._clear_panels()
        if not self._all_errors or self._get_bounds_fn is None:
            return False

        # Helper to get per-word bounds to handle text wrapping properly.
        # If an error is "can be able to", it might wrap across lines.
        # We query the bounds of each word individually.
        def get_word_bounds(err):
            words = err.original_word.split()
            offset = err.offset
            bounds_list = []
            for w in words:
                length = len(w)
                b = self._get_bounds_fn(offset, length)
                if b and b[2] > 0:
                    bounds_list.append((b, err))
                offset += length + 1  # naive approximation, assuming single spaces
            return bounds_list

        all_word_bounds = []
        for err in self._all_errors:
            # Query bounds for each individual word inside the error phrase
            all_word_bounds.extend(get_word_bounds(err))

        if not all_word_bounds:
            return False

        # ── Yellow segments (Grammar / Style) ──
        # Drawn individually so they follow wrapped lines perfectly
        for b, err in all_word_bounds:
            if err not in self._spelling_errors:
                self._panels.append(_HighlightPanel(
                    b,
                    on_click=lambda bnd=b: self._on_grammar_click(bnd),
                    color=_YELLOW,
                ))

        # ── Red segments (Spelling) ──
        # Drawn after yellow so they sit on top
        for b, err in all_word_bounds:
            if err in self._spelling_errors:
                self._panels.append(_HighlightPanel(
                    b,
                    on_click=lambda e=err, bnd=b: self._on_spelling_click(e, bnd),
                    color=_RED,
                ))

        return len(self._panels) > 0

    def start_tracking(self):
        self._stop_tracking()
        if not self._all_errors or self._get_bounds_fn is None:
            return
        anchor = self._all_errors[0]
        self._anchor_error = anchor
        self._anchor_bounds = self._get_bounds_fn(anchor.offset, anchor.length)
        self._dispatcher = _MainThreadDispatcher.alloc().init()
        self._dispatcher._manager = self
        self._tracking_active = True
        t = threading.Thread(target=self._tracking_loop, daemon=True)
        self._tracking_thread = t
        t.start()

    def _tracking_loop(self):
        settle_timer = 0.0
        last_seen_bounds = self._anchor_bounds
        hidden = False

        while self._tracking_active:
            time.sleep(0.03)
            if not self._tracking_active:
                break
            if self._anchor_error is None or self._get_bounds_fn is None:
                continue

            current_bounds = self._get_bounds_fn(
                self._anchor_error.offset, self._anchor_error.length
            )

            if current_bounds != self._anchor_bounds:
                if not hidden:
                    self._dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
                        b'hide:', None, False
                    )
                    hidden = True

                if current_bounds != last_seen_bounds:
                    settle_timer = time.time()
                    last_seen_bounds = current_bounds
                elif time.time() - settle_timer > 0.3 and current_bounds is not None:
                    self._anchor_bounds = current_bounds
                    self._dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
                        b'rebuild:', None, False
                    )
                    hidden = False

    def _stop_tracking(self):
        self._tracking_active = False
        self._tracking_thread = None

    def _clear_panels(self):
        for p in self._panels:
            p.hide()
        self._panels.clear()


    def clear(self):
        self._stop_tracking()
        self._clear_panels()
        self._all_errors = []
        self._spelling_errors = []
