"""
macOS Accessibility API wrapper.

read_full_text / replace_full_text / read_selected_text / replace_selected_text
use pyobjc (strings are native ObjC objects, no conversion issues).

get_bounds_for_range / get_cursor_offset
use pure ctypes because they deal with opaque CF types (AXValueRef wrapping
CFRange/CGRect) that pyobjc cannot convert across the ctypes boundary.
"""
import ctypes
import subprocess

# ---------------------------------------------------------------------------
# pyobjc imports for string-based AX operations
# ---------------------------------------------------------------------------
try:
    from ApplicationServices import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyAttributeValue,
        AXUIElementSetAttributeValue,
        kAXFocusedUIElementAttribute,
        kAXSelectedTextAttribute,
        kAXValueAttribute,
        kAXRoleAttribute,
    )
    _AX_AVAILABLE = True
except ImportError:
    _AX_AVAILABLE = False

# ---------------------------------------------------------------------------
# Pure-ctypes setup for CF-type operations (bounds, cursor offset)
# ---------------------------------------------------------------------------

_LIBAX_PATH = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)


class _CFRange(ctypes.Structure):
    _fields_ = [("location", ctypes.c_long), ("length", ctypes.c_long)]


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


# AX attribute name strings (the actual CF string values behind the constants)
_AX_FOCUSED_ELEMENT        = b"AXFocusedUIElement"
_AX_SELECTED_TEXT_RANGE    = b"AXSelectedTextRange"
_AX_BOUNDS_FOR_RANGE       = b"AXBoundsForRange"
_AX_POSITION               = b"AXPosition"
_AX_SIZE                   = b"AXSize"

_LIBCF_PATH = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_kCFStringEncodingUTF8 = 0x08000100


def _cfstr(s: bytes) -> int:
    """Creates a CFStringRef from a bytes literal. Returns raw pointer."""
    libcf = ctypes.cdll.LoadLibrary(_LIBCF_PATH)
    libcf.CFStringCreateWithCString.restype = ctypes.c_void_p
    libcf.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
    ]
    return libcf.CFStringCreateWithCString(None, s, _kCFStringEncodingUTF8)


def _libax():
    """Returns a configured ctypes handle to the ApplicationServices framework."""
    lib = ctypes.cdll.LoadLibrary(_LIBAX_PATH)

    lib.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
    lib.AXUIElementCreateSystemWide.argtypes = []

    lib.AXUIElementCopyAttributeValue.restype = ctypes.c_int
    lib.AXUIElementCopyAttributeValue.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]

    lib.AXUIElementCopyParameterizedAttributeValue.restype = ctypes.c_int
    lib.AXUIElementCopyParameterizedAttributeValue.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]

    lib.AXValueCreate.restype = ctypes.c_void_p
    lib.AXValueCreate.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

    lib.AXValueGetValue.restype = ctypes.c_bool
    lib.AXValueGetValue.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]

    return lib


def _focused_element_ptr(lib) -> int | None:
    """
    Returns the raw AXUIElementRef pointer of the deepest focused element.

    Some apps (Chrome, Electron, Firefox) set the system-level focused element
    to a container (AXWebArea, AXScrollArea) rather than the actual text node.
    The real text element is found by recursively querying
    kAXFocusedUIElementAttribute on each container until we reach a leaf.
    """
    system = lib.AXUIElementCreateSystemWide()
    if not system:
        return None
    focused = ctypes.c_void_p()
    err = lib.AXUIElementCopyAttributeValue(
        system, _cfstr(_AX_FOCUSED_ELEMENT), ctypes.byref(focused),
    )
    if err or not focused.value:
        return None

    # Descend up to 8 levels to reach the actual text element.
    for _ in range(8):
        inner = ctypes.c_void_p()
        err = lib.AXUIElementCopyAttributeValue(
            focused.value, _cfstr(_AX_FOCUSED_ELEMENT), ctypes.byref(inner),
        )
        if err or not inner.value or inner.value == focused.value:
            break
        focused = inner

    return focused.value


def get_focused_pid() -> int | None:
    """Returns the process ID (PID) of the current focused AX element."""
    try:
        lib = _libax()
        lib.AXUIElementGetPid.restype = ctypes.c_int
        lib.AXUIElementGetPid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]

        system = lib.AXUIElementCreateSystemWide()
        if not system:
            return None
        
        focused = ctypes.c_void_p()
        err = lib.AXUIElementCopyAttributeValue(
            system, _cfstr(_AX_FOCUSED_ELEMENT), ctypes.byref(focused),
        )
        if err or not focused.value:
            return None

        pid = ctypes.c_int(0)
        err = lib.AXUIElementGetPid(focused.value, ctypes.byref(pid))
        if err == 0:
            return pid.value
        return None
    except Exception as e:
        print(f"[ax_monitor.get_focused_pid] err: {e}")
        return None


def _element_frame(lib, focused: int):
    """
    Returns (x, y, w, h) of the focused element in Quartz screen coords,
    or None if unavailable. Uses kAXPosition + kAXSize.
    """
    pos_ref = ctypes.c_void_p()
    err = lib.AXUIElementCopyAttributeValue(focused, _cfstr(_AX_POSITION), ctypes.byref(pos_ref))
    if err or not pos_ref.value:
        return None
    pt = _CGPoint()
    if not lib.AXValueGetValue(pos_ref.value, 1, ctypes.byref(pt)):  # 1=kAXValueCGPointType
        return None

    sz_ref = ctypes.c_void_p()
    err = lib.AXUIElementCopyAttributeValue(focused, _cfstr(_AX_SIZE), ctypes.byref(sz_ref))
    if err or not sz_ref.value:
        return None
    sz = _CGSize()
    if not lib.AXValueGetValue(sz_ref.value, 2, ctypes.byref(sz)):  # 2=kAXValueCGSizeType
        return None

    return pt.x, pt.y, sz.width, sz.height


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------

def _check_permission() -> bool:
    if not _AX_AVAILABLE:
        return False
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        trusted = AXIsProcessTrustedWithOptions(None)
        if not trusted:
            subprocess.run([
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ])
        return bool(trusted)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Text read / write  (pyobjc — strings work fine)
# ---------------------------------------------------------------------------

def _deep_focused_element_pyobjc():
    """Returns the deepest focused AX element using pyobjc, or None."""
    system = AXUIElementCreateSystemWide()
    err, focused = AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute, None)
    if err or focused is None:
        return None
    for _ in range(8):
        err2, inner = AXUIElementCopyAttributeValue(focused, kAXFocusedUIElementAttribute, None)
        if err2 or inner is None or inner == focused:
            break
        focused = inner
    return focused


def read_full_text() -> str | None:
    if not _AX_AVAILABLE:
        return None
    try:
        focused = _deep_focused_element_pyobjc()
        if focused is None:
            return None
        err, value = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        if err or value is None:
            return None
        return str(value)
    except Exception:
        return None


def replace_full_text(new_text: str) -> bool:
    if not _AX_AVAILABLE:
        return False
    try:
        focused = _deep_focused_element_pyobjc()
        if focused is None:
            return False
        err = AXUIElementSetAttributeValue(focused, kAXValueAttribute, new_text)
        if err == 0:
            return True
        # Fallback: select all + replace selection
        import Quartz, time
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(src, 0x00, down)  # 'a'
            Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.06)
        err = AXUIElementSetAttributeValue(focused, kAXSelectedTextAttribute, new_text)
        return err == 0
    except Exception:
        return False


def read_selected_text() -> str | None:
    if not _AX_AVAILABLE:
        return None
    try:
        focused = _deep_focused_element_pyobjc()
        if focused is None:
            return None
        err, text = AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute, None)
        return str(text) if (not err and text) else None
    except Exception:
        return None


def replace_selected_text(new_text: str) -> bool:
    if not _AX_AVAILABLE:
        return False
    try:
        focused = _deep_focused_element_pyobjc()
        if focused is None:
            return False
        err = AXUIElementSetAttributeValue(focused, kAXSelectedTextAttribute, new_text)
        return err == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Bounds / cursor  (pure ctypes — CF types, no pyobjc wrappers)
# ---------------------------------------------------------------------------

def get_cursor_offset() -> int | None:
    """Returns the cursor position (char offset) in the focused element."""
    try:
        lib = _libax()
        focused = _focused_element_ptr(lib)
        if not focused:
            return None

        range_ref = ctypes.c_void_p()
        err = lib.AXUIElementCopyAttributeValue(
            focused, _cfstr(_AX_SELECTED_TEXT_RANGE), ctypes.byref(range_ref),
        )
        if err or not range_ref.value:
            return None

        cfrange = _CFRange()
        ok = lib.AXValueGetValue(range_ref.value, 4, ctypes.byref(cfrange))  # 4=CFRange
        return int(cfrange.location) if ok else None
    except Exception as e:
        print(f"[ax_monitor.get_cursor_offset] {e}")
        return None


def get_mouse_position() -> tuple[float, float] | None:
    """Returns current mouse position in Cocoa screen coords."""
    try:
        from AppKit import NSEvent, NSScreen
        loc = NSEvent.mouseLocation()
        return loc.x, loc.y
    except Exception:
        return None


def get_bounds_for_range(offset: int, length: int) -> tuple[float, float, float, float] | None:
    """
    Returns (x, y, w, h) in Cocoa screen coords (bottom-left origin)
    for the given character range in the focused text element.
    Uses pure ctypes to bypass pyobjc's opaque AXValueRef handling.
    """
    if not _AX_AVAILABLE:
        return None
    try:
        from AppKit import NSScreen

        lib = _libax()
        focused = _focused_element_ptr(lib)
        if not focused:
            return None

        cfr = _CFRange(offset, length)
        ax_range = lib.AXValueCreate(4, ctypes.byref(cfr))  # 4 = kAXValueCFRangeType
        if not ax_range:
            return None

        bounds_ref = ctypes.c_void_p()
        err = lib.AXUIElementCopyParameterizedAttributeValue(
            focused, _cfstr(_AX_BOUNDS_FOR_RANGE), ax_range, ctypes.byref(bounds_ref),
        )
        if err or not bounds_ref.value:
            print(f"[ax_monitor] AXCopyParam err={err}")
            return None

        rect = _CGRect()
        ok = lib.AXValueGetValue(bounds_ref.value, 3, ctypes.byref(rect))  # 3 = CGRect
        if not ok:
            return None

        qx = rect.origin.x
        qy = rect.origin.y
        w  = rect.size.width
        h  = rect.size.height
        print(f"[ax_monitor] raw rect: ({qx:.1f},{qy:.1f}) {w:.1f}×{h:.1f}")

        # AX / Quartz uses: origin = top-left of primary (menubar) screen,
        # y increases downward.
        # Cocoa / NSPanel uses: origin = bottom-left of primary screen,
        # y increases upward.
        # The ALWAYS-CORRECT conversion is: y_cocoa = primary_h - y_quartz
        # where primary_h is the height of the primary (menubar) screen.
        # Using NSScreen.mainScreen() is WRONG on multi-display setups because
        # mainScreen() returns the screen with the key window, not the primary.
        from AppKit import NSScreen
        all_screens = NSScreen.screens()
        # The primary screen (menubar) has its Cocoa origin at (0, 0).
        primary_screen = next(
            (s for s in all_screens
             if s.frame().origin.x == 0.0 and s.frame().origin.y == 0.0),
            all_screens[0] if all_screens else NSScreen.mainScreen(),
        )
        primary_h = primary_screen.frame().size.height

        # Some apps return position but not dimensions — estimate them
        if w <= 1:
            w = float(max(int(length * 7.5), 12))
        if h <= 1:
            h = 18.0

        y_cocoa = primary_h - qy - h

        # Accept coordinates that land on any connected display.
        # Use strict bounds (10px margin) so clearly off-screen values
        # (e.g. y=-18 from Chrome returning y=screen_h) are rejected.
        def _on_any_screen(cx, cy):
            for s in all_screens:
                f = s.frame()
                margin = 10
                if (f.origin.x - margin <= cx <= f.origin.x + f.size.width + margin and
                        f.origin.y - margin <= cy <= f.origin.y + f.size.height + margin):
                    return True
            return False

        if (qx == 0.0 and qy == 0.0) or not _on_any_screen(qx, y_cocoa):
            print(f"[ax_monitor] BoundsForRange gave bad coords (y_cocoa={y_cocoa:.0f}), trying element frame fallback")
            frame = _element_frame(lib, focused)
            if frame:
                fx, fy, fw, fh = frame
                print(f"[ax_monitor] element frame: ({fx:.0f},{fy:.0f}) {fw:.0f}×{fh:.0f}")
                y_cocoa = primary_h - fy - h
                if _on_any_screen(fx, y_cocoa):
                    qx = fx + 8
                    print(f"[ax_monitor] fallback bounds: ({qx:.0f},{y_cocoa:.0f} {w:.0f}×{h:.0f})")
                    return qx, y_cocoa, w, h
            return None

        print(f"[ax_monitor] bounds offset={offset} len={length} → ({qx:.0f},{y_cocoa:.0f} {w:.0f}×{h:.0f})")
        return qx, y_cocoa, w, h

    except Exception as e:
        print(f"[ax_monitor.get_bounds_for_range] {e}")
        return None
