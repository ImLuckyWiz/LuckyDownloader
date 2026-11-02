"""
Frameless window management: native Win32 frame styles, DWM shadow,
Snap Layouts, hit-testing, and edge grips fallback (v2.6.1).

Architectural layers:
1. Pure functions & enums (no Qt, no ctypes): Region, hit_test, resized_rect, shrink_for_autohide.
2. Windows Native Glue (ctypes): NativeFrame handles WM_NCCALCSIZE, WM_NCHITTEST, DWM shadow.
3. Edge Grips fallback (Qt): 8 edge/corner grip widgets calling startSystemResize or manual resize.
4. FrameController: High-level controller connecting MainWindow to NativeFrame / EdgeGrips.
"""

from __future__ import annotations

import enum
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QCursor, QMouseEvent, QWindow
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from qt_ui.main_window import MainWindow
    from qt_ui.titlebar import CustomTitleBar

# ---------------------------------------------------------------------------
# 1. Pure layer (no Qt, no ctypes)
# ---------------------------------------------------------------------------

class Region(enum.IntEnum):
    """Hit-test regions matching Win32 HT* constants."""
    NOWHERE = 0
    CLIENT = 1
    CAPTION = 2
    MINBUTTON = 8
    MAXBUTTON = 9
    LEFT = 10
    RIGHT = 11
    TOP = 12
    TOPLEFT = 13
    TOPRIGHT = 14
    BOTTOM = 15
    BOTTOMLEFT = 16
    BOTTOMRIGHT = 17
    CLOSE = 20


# Default logical metrics
BORDER_THICKNESS = 6
CORNER_SIZE = 12
TITLEBAR_HEIGHT = 32


def hit_test(
    x: float,
    y: float,
    width: float,
    height: float,
    border: float = BORDER_THICKNESS,
    corner_size: float = CORNER_SIZE,
    bar_height: float = TITLEBAR_HEIGHT,
    maximized: bool = False,
    client_rects: list[tuple[float, float, float, float]] | None = None,
    max_button_rect: tuple[float, float, float, float] | None = None,
) -> Region:
    """Determine the hit region for point (x, y) in a window of size (width, height).

    client_rects is a list of (rx, ry, rw, rh) for interactive widgets in the title bar
    (such as icon, search entry, or buttons) that should receive normal mouse clicks.
    """
    if x < 0 or y < 0 or x >= width or y >= height:
        return Region.NOWHERE

    # 1. When maximized, borders cannot be resized
    if not maximized:
        # Check corners first
        top = y < border
        bottom = y >= height - border
        left = x < border
        right = x >= width - border

        corner_top = y < corner_size
        corner_bottom = y >= height - corner_size
        corner_left = x < corner_size
        corner_right = x >= width - corner_size

        if corner_top and corner_left:
            return Region.TOPLEFT
        if corner_top and corner_right:
            return Region.TOPRIGHT
        if corner_bottom and corner_left:
            return Region.BOTTOMLEFT
        if corner_bottom and corner_right:
            return Region.BOTTOMRIGHT

        # Edges
        if top:
            return Region.TOP
        if bottom:
            return Region.BOTTOM
        if left:
            return Region.LEFT
        if right:
            return Region.RIGHT

    # 2. Inside the Title Bar area
    if y < bar_height:
        # Check maximize button for Snap Layouts
        if max_button_rect:
            mx, my, mw, mh = max_button_rect
            if mx <= x < mx + mw and my <= y < my + mh:
                return Region.MAXBUTTON

        # Check client widgets in the bar (buttons, inputs)
        if client_rects:
            for cx, cy, cw, ch in client_rects:
                if cx <= x < cx + cw and cy <= y < cy + ch:
                    return Region.CLIENT

        return Region.CAPTION

    return Region.CLIENT


def resized_rect(
    x: int,
    y: int,
    w: int,
    h: int,
    edge: Region,
    dx: int,
    dy: int,
    min_w: int = 950,
    min_h: int = 560,
) -> tuple[int, int, int, int]:
    """Calculate new (x, y, w, h) for a manual resize drag on `edge` by delta (dx, dy)."""
    new_x, new_y, new_w, new_h = x, y, w, h

    # Horizontal
    if edge in (Region.LEFT, Region.TOPLEFT, Region.BOTTOMLEFT):
        cand_w = w - dx
        if cand_w >= min_w:
            new_x = x + dx
            new_w = cand_w
        else:
            new_x = x + (w - min_w)
            new_w = min_w
    elif edge in (Region.RIGHT, Region.TOPRIGHT, Region.BOTTOMRIGHT):
        new_w = max(min_w, w + dx)

    # Vertical
    if edge in (Region.TOP, Region.TOPLEFT, Region.TOPRIGHT):
        cand_h = h - dy
        if cand_h >= min_h:
            new_y = y + dy
            new_h = cand_h
        else:
            new_y = y + (h - min_h)
            new_h = min_h
    elif edge in (Region.BOTTOM, Region.BOTTOMLEFT, Region.BOTTOMRIGHT):
        new_h = max(min_h, h + dy)

    return new_x, new_y, new_w, new_h


def shrink_for_autohide(
    rect: tuple[int, int, int, int],
    autohide_edges: tuple[bool, bool, bool, bool],  # (left, top, right, bottom)
) -> tuple[int, int, int, int]:
    """Shrink a maximized window rect by 1px on edges with an auto-hiding taskbar."""
    x, y, w, h = rect
    ah_left, ah_top, ah_right, ah_bottom = autohide_edges
    if ah_left:
        x += 1
        w -= 1
    if ah_top:
        y += 1
        h -= 1
    if ah_right:
        w -= 1
    if ah_bottom:
        h -= 1
    return x, y, w, h


def calculate_client_rect(
    proposed_rect: tuple[int, int, int, int],  # (left, top, right, bottom)
    is_zoomed: bool,
    work_area: tuple[int, int, int, int],      # (left, top, right, bottom)
    autohide_edges: tuple[bool, bool, bool, bool] = (False, False, False, False),
) -> tuple[int, int, int, int]:
    """Calculate the client rect for WM_NCCALCSIZE.

    When zoomed (maximized), client rect is set to the monitor work area
    (shrunk by 1px on edges with an auto-hiding taskbar).
    When not zoomed (normal or drag-restoring), the proposed rectangle
    is left untouched so client matches window bounds exactly.
    """
    if not is_zoomed:
        return proposed_rect

    wa_left, wa_top, wa_right, wa_bottom = work_area
    wa_w = wa_right - wa_left
    wa_h = wa_bottom - wa_top
    shrunk_x, shrunk_y, shrunk_w, shrunk_h = shrink_for_autohide(
        (wa_left, wa_top, wa_w, wa_h), autohide_edges
    )
    return (shrunk_x, shrunk_y, shrunk_x + shrunk_w, shrunk_y + shrunk_h)


def _frame_debug_log(msg: str) -> None:
    """Diagnostic logger for frameless window events, active only when LUCKYTWITCH_FRAME_DEBUG=1."""
    if os.environ.get("LUCKYTWITCH_FRAME_DEBUG") != "1":
        return
    try:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}\n"
        sys.stderr.write(line)
        sys.stderr.flush()
        log_path = Path.cwd() / "frame_debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 2. Windows Native Glue (Win32 & DWM via ctypes)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_SYSMENU = 0x00080000

    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    WM_NCMOUSEMOVE = 0x00A0
    WM_NCLBUTTONDOWN = 0x00A1
    WM_NCLBUTTONUP = 0x00A2
    WM_NCMOUSELEAVE = 0x02A2
    WM_GETMINMAXINFO = 0x0024
    WM_SIZE = 0x0005
    WM_WINDOWPOSCHANGING = 0x0046
    WM_WINDOWPOSCHANGED = 0x0047

    MONITOR_DEFAULTTONEAREST = 2

    class MARGINS(ctypes.Structure):
        _fields_ = [
            ("cxLeftWidth", ctypes.c_int),
            ("cxRightWidth", ctypes.c_int),
            ("cyTopHeight", ctypes.c_int),
            ("cyBottomHeight", ctypes.c_int),
        ]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [
            ("rgrc", RECT * 3),
            ("lppos", ctypes.c_void_p),
        ]

    class POINT(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_long),
            ("y", ctypes.c_long),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uCallbackMessage", wintypes.UINT),
            ("uEdge", wintypes.UINT),
            ("rc", RECT),
            ("lParam", wintypes.LPARAM),
        ]

    ABM_GETSTATE = 0x00000004
    ABM_GETTASKBARPOS = 0x00000005
    ABS_AUTOHIDE = 0x00000001
    ABE_LEFT = 0
    ABE_TOP = 1
    ABE_RIGHT = 2
    ABE_BOTTOM = 3


class NativeFrame:
    """Manages native Win32 window styles, DWM frame extension, and message handling."""

    def __init__(self, window: MainWindow):
        self.window = window
        self.hwnd: int | None = None
        self._styles_applied = False
        self._max_btn_hovered = False
        self._max_btn_pressed = False
        self._last_zoomed: bool | None = None

    def init_window(self) -> bool:
        """Apply Win32 styles and DWM frame extension once window handle is valid."""
        if sys.platform != "win32":
            return False

        wh = self.window.windowHandle()
        if wh is None:
            return False

        self.hwnd = int(wh.winId())
        if not self.hwnd:
            return False

        if not self._styles_applied:
            # Add native frame styles so Windows gives Aero Snap, shadow, min/max animation
            style = user32.GetWindowLongW(self.hwnd, GWL_STYLE)
            user32.SetWindowLongW(
                self.hwnd,
                GWL_STYLE,
                style | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU,
            )

            # Extend 1px frame into client area to trigger DWM window shadow and rounded corners
            margins = MARGINS(0, 0, 1, 0)
            dwmapi.DwmExtendFrameIntoClientArea(self.hwnd, ctypes.byref(margins))

            # Force redraw of frame
            user32.SetWindowPos(
                self.hwnd, 0, 0, 0, 0, 0,
                0x0001 | 0x0002 | 0x0020 | 0x0040,  # SWP_NOSIZE | SWP_NOMOVE | SWP_FRAMECHANGED | SWP_NOACTIVATE
            )
            self._styles_applied = True

        return True

    def get_autohide_taskbar_edges(self) -> tuple[bool, bool, bool, bool]:
        """Check if any edge of the primary display has an auto-hiding taskbar."""
        if sys.platform != "win32":
            return (False, False, False, False)
        try:
            shell32 = ctypes.windll.shell32
            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
            if not (state & ABS_AUTOHIDE):
                return (False, False, False, False)

            # Check taskbar position
            if shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(abd)):
                edge = abd.uEdge
                return (edge == ABE_LEFT, edge == ABE_TOP, edge == ABE_RIGHT, edge == ABE_BOTTOM)
        except Exception:
            pass
        return (False, False, False, False)

    def handle_native_event(self, event_type, message) -> tuple[bool, int]:
        """Process Win32 MSG in nativeEvent."""
        if sys.platform != "win32":
            return False, 0

        try:
            ev = bytes(event_type) if hasattr(event_type, "__bytes__") or isinstance(event_type, (bytes, bytearray, QByteArray)) else str(event_type).encode("ascii", "ignore")
            if ev not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0

            addr = int(message)
            msg = wintypes.MSG.from_address(addr)
            hwnd = msg.hWnd

            # 1. WM_NCCALCSIZE: Remove standard titlebar and borders
            if msg.message == WM_NCCALCSIZE:
                if msg.wParam:
                    lparam_addr = int(msg.lParam)
                    if lparam_addr < 0:
                        lparam_addr &= 0xFFFFFFFFFFFFFFFF
                    params = NCCALCSIZE_PARAMS.from_address(lparam_addr)
                    is_zoomed = bool(user32.IsZoomed(hwnd))
                    proposed = (
                        int(params.rgrc[0].left),
                        int(params.rgrc[0].top),
                        int(params.rgrc[0].right),
                        int(params.rgrc[0].bottom),
                    )

                    work_area = (0, 0, 0, 0)
                    if is_zoomed:
                        # Find monitor containing proposed window rect
                        hmon = user32.MonitorFromRect(ctypes.byref(params.rgrc[0]), MONITOR_DEFAULTTONEAREST)
                        if not hmon:
                            hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                        mi = MONITORINFO()
                        mi.cbSize = ctypes.sizeof(MONITORINFO)
                        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                            work_area = (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom)

                    autohide = self.get_autohide_taskbar_edges() if is_zoomed else (False, False, False, False)
                    new_client = calculate_client_rect(proposed, is_zoomed, work_area, autohide)

                    params.rgrc[0].left = new_client[0]
                    params.rgrc[0].top = new_client[1]
                    params.rgrc[0].right = new_client[2]
                    params.rgrc[0].bottom = new_client[3]

                    _frame_debug_log(
                        f"WM_NCCALCSIZE: is_zoomed={is_zoomed} qt_max={self.window.isMaximized()} "
                        f"proposed={proposed} -> client={new_client}"
                    )
                    return True, 0

            # 2. WM_NCHITTEST: Hit-test window borders, caption, and maximize button
            elif msg.message == WM_NCHITTEST:
                screen_x = ctypes.c_short(msg.lParam & 0xFFFF).value
                screen_y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

                pt = POINT(screen_x, screen_y)
                user32.ScreenToClient(hwnd, ctypes.byref(pt))

                dpr = self.window.devicePixelRatio()
                x = pt.x / dpr
                y = pt.y / dpr
                w = self.window.width()
                h = self.window.height()

                client_rects = []
                max_button_rect = None

                tb: CustomTitleBar | None = getattr(self.window, "title_bar", None)
                if tb is not None:
                    for child in (tb.icon_label, tb.min_btn, tb.close_btn):
                        if child.isVisible():
                            geo = child.geometry()
                            client_rects.append((float(geo.x()), float(geo.y()), float(geo.width()), float(geo.height())))
                    if tb.max_btn.isVisible():
                        geo = tb.max_btn.geometry()
                        max_button_rect = (float(geo.x()), float(geo.y()), float(geo.width()), float(geo.height()))

                is_zoomed = bool(user32.IsZoomed(hwnd))
                reg = hit_test(
                    x, y, w, h,
                    border=BORDER_THICKNESS,
                    corner_size=CORNER_SIZE,
                    bar_height=TITLEBAR_HEIGHT if tb else 0,
                    maximized=is_zoomed,
                    client_rects=client_rects,
                    max_button_rect=max_button_rect,
                )
                return True, int(reg)

            # 3. Handle Snap Layouts flyout interactions on maximize button
            elif msg.message == WM_NCMOUSEMOVE:
                if msg.wParam == Region.MAXBUTTON:
                    if not self._max_btn_hovered:
                        self._max_btn_hovered = True
                        self._update_max_button_visual(hover=True, pressed=self._max_btn_pressed)
                else:
                    if self._max_btn_hovered:
                        self._max_btn_hovered = False
                        self._update_max_button_visual(hover=False, pressed=False)

            elif msg.message == WM_NCLBUTTONDOWN:
                if msg.wParam == Region.MAXBUTTON:
                    self._max_btn_pressed = True
                    self._update_max_button_visual(hover=True, pressed=True)
                    return True, 0

            elif msg.message == WM_NCLBUTTONUP:
                if msg.wParam == Region.MAXBUTTON:
                    self._max_btn_pressed = False
                    self._update_max_button_visual(hover=self._max_btn_hovered, pressed=False)
                    is_zoomed = bool(user32.IsZoomed(hwnd))
                    if is_zoomed:
                        self.window.showNormal()
                    else:
                        self.window.showMaximized()
                    if getattr(self.window, "title_bar", None):
                        self.window.title_bar.update_maximized_state(not is_zoomed)
                    return True, 0

            elif msg.message == WM_NCMOUSELEAVE:
                if self._max_btn_hovered or self._max_btn_pressed:
                    self._max_btn_hovered = False
                    self._max_btn_pressed = False
                    self._update_max_button_visual(hover=False, pressed=False)

            elif msg.message in (WM_SIZE, WM_WINDOWPOSCHANGED):
                is_zoomed = bool(user32.IsZoomed(hwnd))
                if getattr(self, "_last_zoomed", None) != is_zoomed:
                    self._last_zoomed = is_zoomed
                    tb = getattr(self.window, "title_bar", None)
                    if tb is not None:
                        tb.update_maximized_state(is_zoomed)
                    _frame_debug_log(f"STATE_CHANGED (native): is_zoomed={is_zoomed}")

        except Exception:
            return False, 0

        return False, 0

    def _update_max_button_visual(self, hover: bool, pressed: bool) -> None:
        tb = getattr(self.window, "title_bar", None)
        if tb and hasattr(tb, "max_btn"):
            if hasattr(tb.max_btn, "set_native_state"):
                tb.max_btn.set_native_state(hover=hover, pressed=pressed)


# ---------------------------------------------------------------------------
# 3. Edge Grips Fallback (Linux / macOS / --grips-only)
# ---------------------------------------------------------------------------

class Grip(QWidget):
    """Transparent edge/corner widget that triggers OS resize or manual resize."""

    def __init__(self, parent: QWidget, region: Region, cursor_shape: Qt.CursorShape):
        super().__init__(parent)
        self.region = region
        self.setCursor(cursor_shape)
        self._press_pos: QPoint | None = None
        self._init_geom: QRect | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            wh = self.window().windowHandle()
            if wh is not None and hasattr(wh, "startSystemResize"):
                # Map Region to Qt.Edge
                edge_map = {
                    Region.LEFT: Qt.Edge.LeftEdge,
                    Region.RIGHT: Qt.Edge.RightEdge,
                    Region.TOP: Qt.Edge.TopEdge,
                    Region.BOTTOM: Qt.Edge.BottomEdge,
                    Region.TOPLEFT: Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
                    Region.TOPRIGHT: Qt.Edge.TopEdge | Qt.Edge.RightEdge,
                    Region.BOTTOMLEFT: Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
                    Region.BOTTOMRIGHT: Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
                }
                qt_edge = edge_map.get(self.region)
                if qt_edge and wh.startSystemResize(qt_edge):
                    event.accept()
                    return

            # Fallback manual resize
            self._press_pos = event.globalPosition().toPoint()
            self._init_geom = self.window().geometry()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_pos is not None and self._init_geom is not None:
            cur = event.globalPosition().toPoint()
            dx = cur.x() - self._press_pos.x()
            dy = cur.y() - self._press_pos.y()
            min_size = self.window().minimumSize()
            nx, ny, nw, nh = resized_rect(
                self._init_geom.x(), self._init_geom.y(),
                self._init_geom.width(), self._init_geom.height(),
                self.region, dx, dy,
                min_w=min_size.width(), min_h=min_size.height(),
            )
            self.window().setGeometry(nx, ny, nw, nh)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_pos = None
        self._init_geom = None
        super().mouseReleaseEvent(event)


class EdgeGrips:
    """Manages the 8 edge and corner resize grip widgets."""

    def __init__(self, window: QWidget, thickness: int = BORDER_THICKNESS, corner_size: int = CORNER_SIZE):
        self.window = window
        self.thickness = thickness
        self.corner_size = corner_size

        self.grips = {
            Region.TOP: Grip(window, Region.TOP, Qt.CursorShape.SizeVerCursor),
            Region.BOTTOM: Grip(window, Region.BOTTOM, Qt.CursorShape.SizeVerCursor),
            Region.LEFT: Grip(window, Region.LEFT, Qt.CursorShape.SizeHorCursor),
            Region.RIGHT: Grip(window, Region.RIGHT, Qt.CursorShape.SizeHorCursor),
            Region.TOPLEFT: Grip(window, Region.TOPLEFT, Qt.CursorShape.SizeFDiagCursor),
            Region.TOPRIGHT: Grip(window, Region.TOPRIGHT, Qt.CursorShape.SizeBDiagCursor),
            Region.BOTTOMLEFT: Grip(window, Region.BOTTOMLEFT, Qt.CursorShape.SizeBDiagCursor),
            Region.BOTTOMRIGHT: Grip(window, Region.BOTTOMRIGHT, Qt.CursorShape.SizeFDiagCursor),
        }
        for g in self.grips.values():
            g.raise_()

    def update_geometry(self, w: int, h: int, is_maximized: bool) -> None:
        """Reposition grips along the window perimeter, or hide them when maximized."""
        if is_maximized:
            for g in self.grips.values():
                g.hide()
            return

        t = self.thickness
        c = self.corner_size

        # Show and position corners
        self.grips[Region.TOPLEFT].setGeometry(0, 0, c, c)
        self.grips[Region.TOPRIGHT].setGeometry(w - c, 0, c, c)
        self.grips[Region.BOTTOMLEFT].setGeometry(0, h - c, c, c)
        self.grips[Region.BOTTOMRIGHT].setGeometry(w - c, h - c, c, c)

        # Show and position edges
        self.grips[Region.TOP].setGeometry(c, 0, max(0, w - 2 * c), t)
        self.grips[Region.BOTTOM].setGeometry(c, h - t, max(0, w - 2 * c), t)
        self.grips[Region.LEFT].setGeometry(0, c, t, max(0, h - 2 * c))
        self.grips[Region.RIGHT].setGeometry(w - t, c, t, max(0, h - 2 * c))

        for g in self.grips.values():
            g.show()
            g.raise_()


# ---------------------------------------------------------------------------
# 4. FrameController (Master Coordinator)
# ---------------------------------------------------------------------------

class FrameController:
    """Coordinates window frame styles, hit-testing, and resize grips for MainWindow."""

    def __init__(self, window: MainWindow):
        self.window = window
        self.native_mode = (
            sys.platform == "win32"
            and "--grips-only" not in sys.argv
            and os.environ.get("LUCKYTWITCH_GRIPS_ONLY") != "1"
        )
        self.native_frame = NativeFrame(window) if self.native_mode else None
        self.grips: EdgeGrips | None = None

    def on_show(self) -> None:
        """Called in MainWindow.showEvent once native window handle exists."""
        if self.native_frame is not None:
            ok = self.native_frame.init_window()
            if not ok:
                # If native initialization failed, fallback to grips
                self.native_mode = False
                self.native_frame = None

        if not self.native_mode and self.grips is None:
            self.grips = EdgeGrips(self.window)
            self.grips.update_geometry(self.window.width(), self.window.height(), self.window.isMaximized())

    def on_resize(self, w: int, h: int, is_maximized: bool) -> None:
        """Called in MainWindow.resizeEvent to refresh grips if active."""
        if self.grips is not None:
            self.grips.update_geometry(w, h, is_maximized)

    def on_state_change(self, is_maximized: bool) -> None:
        """Called on window state changes (maximize/restore)."""
        if self.grips is not None:
            self.grips.update_geometry(self.window.width(), self.window.height(), is_maximized)

    def handle_native_event(self, event_type: str, message: int) -> tuple[bool, int]:
        """Delegate nativeEvent to NativeFrame if in native Win32 mode."""
        if self.native_frame is not None:
            return self.native_frame.handle_native_event(event_type, message)
        return False, 0
