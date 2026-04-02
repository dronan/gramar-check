Correction card — Floating NSPanel popover.

show_single  clicked a red (spelling) underline  → compact word card
show_all     clicked a yellow (grammar) underline → sentence diff card

Clicking outside the card hides it but keeps the underlines alive.
"""
import objc
from objc import super as objc_super
from Foundation import NSObject, NSMakeRect, NSMutableAttributedString, NSAttributedString, NSMakePoint
from AppKit import (
    NSPanel,
    NSBox,
    NSView,
    NSVisualEffectView,
    NSColor,
    NSButton,
    NSTextField,
    NSBezierPath,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
    NSFont,
    NSBezelStyleRounded,
    NSBezelStyleSmallSquare,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
    NSStrikethroughStyleAttributeName,
    NSEvent,
    NSLineBreakByTruncatingTail,
)

_NON_ACTIVATING = 1 << 7
_BORDERLESS = 0
_MATERIAL_POPOVER = 6   # NSVisualEffectMaterialPopover
_BLEND_BEHIND    = 0    # NSVisualEffectBlendingModeBehindWindow
_STATE_ACTIVE    = 1    # NSVisualEffectStateActive

# Brand colors
_GREEN       = (0.08, 0.53, 0.24, 1.0)   # Brand green
_GREEN_LIGHT = (0.08, 0.53, 0.24, 0.10)  # green tint for row hover bg
_RED_TEXT    = (0.72, 0.10, 0.10, 1.0)   # strikethrough red
_YELLOW_HDR  = (0.55, 0.38, 0.00, 1.0)   # amber for grammar header
_SEPARATOR   = (0.0, 0.0, 0.0, 0.10)     # subtle separator


class _PatchedError:
    def __init__(self, original_error, new_replacement: str):
        self.offset      = original_error.offset
        self.length      = original_error.length
        self.replacements = [new_replacement]
        self.original_word = original_error.original_word
        self.message     = original_error.message
        self.category    = original_error.category


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


class _RowView(NSView):
    """Full-width clickable row with hover highlight."""
    def initWithFrame_(self, frame):
        self = objc_super(_RowView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = None
        self._hover = False
        return self

    def drawRect_(self, dirty_rect):
        if self._hover:
            NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.04).setFill()
            NSBezierPath.fillRect_(self.bounds())

    def mouseEntered_(self, event):
        self._hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self._hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()

    def acceptsFirstMouse_(self, event):
        return True

    def updateTrackingAreas(self):
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        from AppKit import NSTrackingArea
        options = 0x01 | 0x02 | 0x20  # mouseEntered/Exited + active always + in view
        area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), options, self, None
        )
        self.addTrackingArea_(area)


class CorrectionCard:
    # Single spelling card
    W_S, H_S = 320, 182
    # Multi grammar card
    W_M, H_M = 380, 200

    def __init__(self):
        self._panel   = None
        self._handlers: list[_Handler] = []
        self._monitor = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_single(self, x, y, error, on_accept, on_dismiss):
        """
        Spelling correction card:
          [header]   Correct your spelling
          [big bold green suggestion word]
          [small grey explanation]
          ─────────────────────────────
          [row] ✓  Accept
          [row] 📖 Add to dictionary
          [row] ✕  Dismiss
          [row] ✦  Rewrite with AI
        Layout: rows grow upward from bottom; content sits above separator.
        """
        self.hide()
        W = self.W_S
        suggestion = error.replacements[0] if error.replacements else ""
        category_label = (error.category or "Spelling").capitalize()

        # ── Build rows list first so we know the count ─────────────────
        row_h = 36
        BOTTOM_PAD = 8
        rows = []
        if suggestion:
            rows.append(("✓", "Accept", _GREEN,
                          lambda: (self.hide(), on_accept(error))))
        rows.append(("📖", "Add to dictionary", None, lambda: self.hide()))
        rows.append(("✕", "Dismiss", None, lambda: (self.hide(), on_dismiss())))
        if error.original_word:
            rows.append(("✦", "Rewrite with AI", None,
                          lambda: self._do_rewrite(error, on_accept)))

        # ── Height calculation (bottom-up) ─────────────────────────────
        # Rows + padding occupy the bottom; content occupies the top.
        #   sep_y   = bottom of content area  = BOTTOM_PAD + n*row_h
        #   CONTENT = 108 px  (header 24 + suggestion 34 + explanation 20 + gap)
        #   H       = sep_y + CONTENT_H
        CONTENT_H = 110
        sep_y = BOTTOM_PAD + len(rows) * row_h   # separator y in panel coords
        H = sep_y + CONTENT_H

        panel, cv = self._make_panel(W, H)

        # ── Header ─────────────────────────────────────────────────────
        cv.addSubview_(self._label(
            f"Correct your {category_label.lower()}",
            NSMakeRect(16, H - 28, W - 32, 15),
            size=11, color=NSColor.secondaryLabelColor(),
        ))

        # ── Suggestion word — big bold green ─────────
        sug_y = H - 62
        if suggestion:
            sug_tf = NSTextField.alloc().initWithFrame_(
                NSMakeRect(16, sug_y, W - 32, 28)
            )
            sug_str = NSAttributedString.alloc().initWithString_attributes_(
                suggestion,
                {
                    NSFontAttributeName: NSFont.boldSystemFontOfSize_(20),
                    NSForegroundColorAttributeName:
                        NSColor.colorWithRed_green_blue_alpha_(*_GREEN),
                }
            )
            sug_tf.setAttributedStringValue_(sug_str)
            sug_tf.setEditable_(False)
            sug_tf.setBordered_(False)
            sug_tf.setDrawsBackground_(False)
            cv.addSubview_(sug_tf)
        elif error.message:
            cv.addSubview_(self._label(
                error.message[:55], NSMakeRect(16, sug_y, W - 32, 28),
                size=15, color=NSColor.labelColor(),
            ))

        # ── Short explanation message ───────────────────────────────────
        if error.message:
            cv.addSubview_(self._label(
                error.message[:80] + ("…" if len(error.message) > 80 else ""),
                NSMakeRect(16, sep_y + CONTENT_H - 82, W - 32, 14),
                size=10, color=NSColor.tertiaryLabelColor(),
            ))

        # ── Separator ──────────────────────────────────────────────────
        cv.addSubview_(_separator(NSMakeRect(0, sep_y, W, 1)))

        # ── Action rows (stacked above BOTTOM_PAD) ─────────────────────
        for i, (icon, title, color, cb) in enumerate(rows):
            ry = BOTTOM_PAD + (len(rows) - 1 - i) * row_h
            cv.addSubview_(_row_view(
                NSMakeRect(0, ry, W, row_h),
                icon=icon, label=title, color=color, callback=cb,
            ))
            if i < len(rows) - 1:
                cv.addSubview_(_separator(
                    NSMakeRect(16, ry + row_h, W - 16, 1)
                ))

        self._panel = panel
        self._show_at(x, y, H)
        self._install_outside_monitor()



    def show_all(self, x, y, errors, original_text,
                 on_accept_one, on_accept_all, on_dismiss):
        """
        Multi-error correction card (used when clicking a yellow underline
        OR as the fallback when AX bounds are unavailable):

          [header]  Improve your text  ·  N issues
          [diff preview of whole sentence]
          [separator]
          [per-error row] ~~wrong~~  →  right   [✓]  [✕]
          ...
          [separator]
          [✓ Fix all (N)]   [Dismiss]
        """
        self.hide()
        W = self.W_M

        n = len(errors)
        HEADER_H   = 38   # header row
        DIFF_H     = 58   # sentence diff preview
        SEP_H      = 1
        ERR_ROW_H  = 40   # height per individual error row
        BTN_AREA_H = 50   # fix-all + dismiss row
        H = HEADER_H + DIFF_H + SEP_H + n * ERR_ROW_H + SEP_H + BTN_AREA_H

        panel, cv = self._make_panel(W, H)

        # ── Header ─────────────────────────────────────────────────────
        cv.addSubview_(self._label(
            "Improve your text",
            NSMakeRect(16, H - 28, W - 110, 16),
            size=11, color=NSColor.secondaryLabelColor(),
        ))
        cv.addSubview_(self._label(
            f"{n} issue{'s' if n > 1 else ''}",
            NSMakeRect(W - 100, H - 28, 84, 16),
            size=11, color=NSColor.colorWithRed_green_blue_alpha_(*_YELLOW_HDR),
            align_right=True,
        ))

        # ── Sentence diff preview ───────────────────────────────────────
        diff_y = H - HEADER_H - DIFF_H
        diff = self._build_diff_string(original_text, errors)
        if diff:
            tv = NSTextField.alloc().initWithFrame_(
                NSMakeRect(16, diff_y + 6, W - 32, DIFF_H - 10)
            )
            tv.setAttributedStringValue_(diff)
            tv.setEditable_(False); tv.setBordered_(False); tv.setDrawsBackground_(False)
            tv.cell().setWraps_(True)
            cv.addSubview_(tv)

        # ── Separator ──────────────────────────────────────────────────
        sep1_y = diff_y
        cv.addSubview_(_separator(NSMakeRect(0, sep1_y, W, SEP_H)))

        # ── Per-error rows ─────────────────────────────────────────────
        sorted_errors = sorted(errors, key=lambda e: e.offset)
        for i, err in enumerate(sorted_errors):
            row_y = sep1_y - ERR_ROW_H * (i + 1)
            self._add_error_row(cv, err, row_y, W, ERR_ROW_H,
                                on_accept_one, on_dismiss)
            if i < n - 1:
                cv.addSubview_(_separator(NSMakeRect(16, row_y, W - 16, SEP_H)))

        # ── Separator ──────────────────────────────────────────────────
        sep2_y = sep1_y - n * ERR_ROW_H
        cv.addSubview_(_separator(NSMakeRect(0, sep2_y, W, SEP_H)))

        # ── Fix all + Dismiss buttons ───────────────────────────────────
        fix_all_h = self._handler(lambda: (self.hide(), on_accept_all()))
        dismiss_h = self._handler(lambda: (self.hide(), on_dismiss()))

        cv.addSubview_(_filled_button(
            f"✓  Fix all ({n})",
            NSMakeRect(16, 12, 148, 28),
            fix_all_h,
            NSColor.colorWithRed_green_blue_alpha_(*_GREEN),
        ))
        cv.addSubview_(_flat_link_button(
            "Dismiss", NSMakeRect(176, 12, 80, 28), dismiss_h
        ))

        self._panel = panel
        self._show_at(x, y, H)
        self._install_outside_monitor()

    def _add_error_row(self, cv, err, row_y, W, row_h, on_accept_one, on_dismiss):
        """
        A single error row:
          ~~wrong~~  →  replacement   [✓]  [✕]
        """
        suggestion = err.replacements[0] if err.replacements else ""

        # Diff inline label
        label_str = NSMutableAttributedString.alloc().init()
        if err.original_word:
            _ap(label_str, err.original_word, {
                NSFontAttributeName: NSFont.systemFontOfSize_(12),
                NSForegroundColorAttributeName: NSColor.colorWithRed_green_blue_alpha_(*_RED_TEXT),
                NSStrikethroughStyleAttributeName: 2,
            })
            if suggestion:
                _ap(label_str, "  →  ", {
                    NSFontAttributeName: NSFont.systemFontOfSize_(12),
                    NSForegroundColorAttributeName: NSColor.tertiaryLabelColor(),
                })
                _ap(label_str, suggestion, {
                    NSFontAttributeName: NSFont.boldSystemFontOfSize_(12),
                    NSForegroundColorAttributeName: NSColor.colorWithRed_green_blue_alpha_(*_GREEN),
                })
        else:
            _ap(label_str, err.message[:50], {
                NSFontAttributeName: NSFont.systemFontOfSize_(12),
                NSForegroundColorAttributeName: NSColor.labelColor(),
            })

        tf = NSTextField.alloc().initWithFrame_(
            NSMakeRect(14, row_y + (row_h - 18) // 2, W - 90, 18)
        )
        tf.setAttributedStringValue_(label_str)
        tf.setEditable_(False); tf.setBordered_(False); tf.setDrawsBackground_(False)
        cv.addSubview_(tf)

        # Small category badge (SPELLING / GRAMMAR)
        cat = (err.category or "").upper()[:7]
        cat_color = _RED_TEXT if err.category == "Spelling" else _YELLOW_HDR
        cat_lbl = self._label(cat,
            NSMakeRect(14, row_y + 4, 56, 10),
            size=8, color=NSColor.colorWithRed_green_blue_alpha_(*cat_color)
        )
        cv.addSubview_(cat_lbl)

        # ✓ Accept button
        if suggestion:
            accept_h = self._handler(lambda e=err: (self.hide(), on_accept_one(e)))
            acc_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(W - 74, row_y + (row_h - 22) // 2, 28, 22)
            )
            acc_btn.setTitle_("✓")
            acc_btn.setBezelStyle_(NSBezelStyleSmallSquare)
            acc_btn.setTarget_(accept_h)
            acc_btn.setAction_("clicked:")
            try:
                acc_btn.setContentTintColor_(
                    NSColor.colorWithRed_green_blue_alpha_(*_GREEN)
                )
            except Exception:
                pass
            cv.addSubview_(acc_btn)

        # ✕ Dismiss button
        dismiss_h = self._handler(lambda: self.hide())
        dis_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(W - 42, row_y + (row_h - 22) // 2, 28, 22)
        )
        dis_btn.setTitle_("✕")
        dis_btn.setBezelStyle_(NSBezelStyleSmallSquare)
        dis_btn.setTarget_(dismiss_h)
        dis_btn.setAction_("clicked:")
        try:
            dis_btn.setContentTintColor_(NSColor.secondaryLabelColor())
        except Exception:
            pass
        cv.addSubview_(dis_btn)


    def hide(self):
        self._remove_outside_monitor()
        if self._panel:
            self._panel.orderOut_(None)
            self._panel = None
            self._handlers.clear()

    # ------------------------------------------------------------------
    # Outside-click monitor
    # ------------------------------------------------------------------

    def _install_outside_monitor(self):
        self._remove_outside_monitor()
        mask = (1 << 1) | (1 << 3)
        panel_ref = [self._panel]

        def on_global_click(event):
            p = panel_ref[0]
            if p is None:
                return
            loc   = NSEvent.mouseLocation()
            frame = p.frame()
            inside = (frame.origin.x <= loc.x <= frame.origin.x + frame.size.width and
                      frame.origin.y <= loc.y <= frame.origin.y + frame.size.height)
            if not inside:
                p.orderOut_(None)
                panel_ref[0] = None
                self._panel  = None
                self._handlers.clear()

        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, on_global_click,
        )

    def _remove_outside_monitor(self):
        if self._monitor:
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _show_at(self, x, y, h):
        self._panel.setFrameOrigin_((x, y - h - 10))
        self._panel.orderFront_(None)

    def _handler(self, cb) -> _Handler:
        h = _Handler.alloc().init()
        h._cb = cb
        self._handlers.append(h)
        return h

    def _do_rewrite(self, error, on_accept):
        import threading

        def run():
            try:
                from ai_client import rewrite
                result = rewrite(error.original_word or "")
                if on_accept and result:
                    on_accept(_PatchedError(error, result))
                self.hide()
            except Exception as e:
                print(f"[rewrite] {e}")
                self.hide()

        threading.Thread(target=run, daemon=True).start()

    def _make_panel(self, w, h):
        """NSPanel with frosted glass content, rounded corners, and drop shadow."""
        style = _BORDERLESS | _NON_ACTIVATING
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, w, h), style, NSBackingStoreBuffered, False,
        )
        panel.setLevel_(NSFloatingWindowLevel + 2)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)

        ve = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        ve.setMaterial_(_MATERIAL_POPOVER)
        ve.setBlendingMode_(_BLEND_BEHIND)
        ve.setState_(_STATE_ACTIVE)
        ve.setWantsLayer_(True)
        ve.layer().setCornerRadius_(12.0)
        ve.layer().setMasksToBounds_(True)
        ve.layer().setBorderWidth_(0.5)
        ve.layer().setBorderColor_(
            NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.15).CGColor()
        )
        panel.setContentView_(ve)
        return panel, ve

    @staticmethod
    def _build_diff_string(original_text, errors):
        sorted_errors = [e for e in sorted(errors, key=lambda e: e.offset) if e.replacements]
        if not sorted_errors:
            return None

        normal = {NSFontAttributeName: NSFont.systemFontOfSize_(13),
                  NSForegroundColorAttributeName: NSColor.labelColor()}
        strike = {NSFontAttributeName: NSFont.systemFontOfSize_(13),
                  NSForegroundColorAttributeName: NSColor.colorWithRed_green_blue_alpha_(*_RED_TEXT),
                  NSStrikethroughStyleAttributeName: 2}
        green  = {NSFontAttributeName: NSFont.boldSystemFontOfSize_(13),
                  NSForegroundColorAttributeName: NSColor.colorWithRed_green_blue_alpha_(*_GREEN)}

        ctx_start = sorted_errors[0].offset
        while ctx_start > 0 and original_text[ctx_start - 1] not in '\n':
            ctx_start -= 1
        ctx_end = sorted_errors[-1].offset + sorted_errors[-1].length
        while ctx_end < len(original_text) and original_text[ctx_end] not in '\n':
            ctx_end += 1

        result = NSMutableAttributedString.alloc().init()
        pos = ctx_start
        for err in sorted_errors:
            if err.offset < pos:
                continue
            _ap(result, original_text[pos:err.offset], normal)
            _ap(result, original_text[err.offset:err.offset + err.length], strike)
            if err.replacements:
                _ap(result, " " + err.replacements[0], green)
            pos = err.offset + err.length
        _ap(result, original_text[pos:ctx_end], normal)
        return result

    @staticmethod
    def _label(text, frame, size=11, bold=False, color=None, align_right=False):
        tf = NSTextField.alloc().initWithFrame_(frame)
        tf.setStringValue_(text)
        tf.setEditable_(False)
        tf.setBordered_(False)
        tf.setDrawsBackground_(False)
        tf.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if color:
            tf.setTextColor_(color)
        if align_right:
            from AppKit import NSRightTextAlignment
            tf.setAlignment_(NSRightTextAlignment)
        tf.cell().setLineBreakMode_(NSLineBreakByTruncatingTail)
        return tf


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _ap(ms, text, attrs):
    """Append text+attrs to an NSMutableAttributedString."""
    if text:
        ms.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        )


def _separator(frame):
    """A thin 1-pt horizontal line (NSBox as separator)."""
    box = NSBox.alloc().initWithFrame_(frame)
    box.setBoxType_(2)   # NSBoxSeparator
    return box


def _row_view(frame, icon, label, color, callback):
    """Clickable full-width row with icon + label text."""
    view = _RowView.alloc().initWithFrame_(frame)
    view._on_click = callback

    icon_tf = NSTextField.alloc().initWithFrame_(
        NSMakeRect(14, (frame.size.height - 16) / 2, 20, 16)
    )
    icon_tf.setStringValue_(icon)
    icon_tf.setEditable_(False); icon_tf.setBordered_(False); icon_tf.setDrawsBackground_(False)
    icon_tf.setFont_(NSFont.systemFontOfSize_(13))
    view.addSubview_(icon_tf)

    lbl_color = NSColor.colorWithRed_green_blue_alpha_(*color) if color else NSColor.labelColor()
    lbl_tf = NSTextField.alloc().initWithFrame_(
        NSMakeRect(38, (frame.size.height - 16) / 2, frame.size.width - 54, 16)
    )
    lbl_tf.setStringValue_(label)
    lbl_tf.setEditable_(False); lbl_tf.setBordered_(False); lbl_tf.setDrawsBackground_(False)
    lbl_tf.setFont_(NSFont.systemFontOfSize_(13))
    lbl_tf.setTextColor_(lbl_color)
    view.addSubview_(lbl_tf)

    view.updateTrackingAreas()
    return view


def _filled_button(title, frame, handler, color):
    """Green-tinted filled rounded button."""
    btn = NSButton.alloc().initWithFrame_(frame)
    btn.setTitle_(title)
    btn.setBezelStyle_(NSBezelStyleRounded)
    btn.setTarget_(handler)
    btn.setAction_("clicked:")
    btn.setKeyEquivalent_("\r")
    try:
        btn.setContentTintColor_(color)
    except Exception:
        pass
    return btn


def _flat_link_button(title, frame, handler):
    """Borderless secondary text button."""
    btn = NSButton.alloc().initWithFrame_(frame)
    btn.setTitle_(title)
    btn.setBezelStyle_(NSBezelStyleRounded)
    btn.setTarget_(handler)
    btn.setAction_("clicked:")
    try:
        btn.setContentTintColor_(NSColor.secondaryLabelColor())
    except Exception:
        pass
    return btn
