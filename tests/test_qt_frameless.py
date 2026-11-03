"""
Unit and integration tests for frameless window hit-testing, resize logic, and frame controller (v2.6.1).
"""

import sys
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from qt_ui.frameless import (
    BORDER_THICKNESS,
    CORNER_SIZE,
    TITLEBAR_HEIGHT,
    EdgeGrips,
    FrameController,
    Region,
    calculate_client_rect,
    hit_test,
    resized_rect,
    shrink_for_autohide,
)


# ---------------------------------------------------------------------------
# 1. Pure layer unit tests
# ---------------------------------------------------------------------------

def test_hit_test_corners():
    w, h = 1000, 700
    # Top-left corner
    assert hit_test(2, 2, w, h) == Region.TOPLEFT
    # Top-right corner
    assert hit_test(995, 2, w, h) == Region.TOPRIGHT
    # Bottom-left corner
    assert hit_test(2, 695, w, h) == Region.BOTTOMLEFT
    # Bottom-right corner
    assert hit_test(995, 695, w, h) == Region.BOTTOMRIGHT


def test_hit_test_edges():
    w, h = 1000, 700
    # Left edge (not in corner)
    assert hit_test(2, 100, w, h) == Region.LEFT
    # Right edge
    assert hit_test(996, 100, w, h) == Region.RIGHT
    # Top edge (not in corner)
    assert hit_test(500, 2, w, h) == Region.TOP
    # Bottom edge
    assert hit_test(500, 696, w, h) == Region.BOTTOM


def test_hit_test_caption_and_client():
    w, h = 1000, 700
    # Inside titlebar empty space -> CAPTION
    assert hit_test(500, 15, w, h) == Region.CAPTION

    # In client body area -> CLIENT
    assert hit_test(500, 200, w, h) == Region.CLIENT


def test_hit_test_maximized_disables_borders():
    w, h = 1000, 700
    # Corners and edges must NOT return resize regions when maximized
    assert hit_test(2, 2, w, h, maximized=True) == Region.CAPTION
    assert hit_test(2, 100, w, h, maximized=True) == Region.CLIENT
    assert hit_test(500, 698, w, h, maximized=True) == Region.CLIENT


def test_hit_test_interactive_widgets_in_titlebar():
    w, h = 1000, 700
    client_rects = [(10, 0, 100, 32), (950, 0, 46, 32)]  # search entry, close button
    max_button_rect = (900, 0, 46, 32)

    # Point inside maximize button
    assert hit_test(920, 15, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.MAXBUTTON

    # Point inside close button
    assert hit_test(960, 15, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.CLIENT

    # Point in empty caption area
    assert hit_test(500, 15, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.CAPTION


def test_resized_rect_enforces_minimums():
    # Default minimums (min_w=950, min_h=560)
    x, y, w, h = resized_rect(100, 100, 1000, 600, Region.RIGHT, dx=-200, dy=0)
    assert w == 950

    # Attempting to shrink past min_w (900)
    x, y, w, h = resized_rect(100, 100, 950, 600, Region.RIGHT, dx=-100, dy=0, min_w=900, min_h=560)
    assert w == 900

    # Attempting to shrink from left
    x, y, w, h = resized_rect(100, 100, 950, 600, Region.LEFT, dx=100, dy=0, min_w=900, min_h=560)
    assert w == 900
    assert x == 150  # 100 + (950 - 900)


def test_shrink_for_autohide():
    rect = (0, 0, 1920, 1080)
    # Taskbar at bottom
    assert shrink_for_autohide(rect, (False, False, False, True)) == (0, 0, 1920, 1079)
    # Taskbar at left
    assert shrink_for_autohide(rect, (True, False, False, False)) == (1, 0, 1919, 1080)


def test_calculate_client_rect_when_not_zoomed():
    proposed = (100, 100, 1120, 700)
    work_area = (0, 0, 1920, 1040)
    # When not zoomed (normal window or drag-restoring), proposed rect is untouched
    assert calculate_client_rect(proposed, is_zoomed=False, work_area=work_area) == proposed


def test_calculate_client_rect_when_zoomed():
    proposed = (-8, -8, 1928, 1048)
    work_area = (0, 0, 1920, 1040)
    # When zoomed, client rect matches monitor work area
    assert calculate_client_rect(proposed, is_zoomed=True, work_area=work_area) == (0, 0, 1920, 1040)


def test_calculate_client_rect_zoomed_with_autohide():
    proposed = (-8, -8, 1928, 1048)
    work_area = (0, 0, 1920, 1080)
    # With bottom autohide taskbar, shrinks by 1px at bottom
    res = calculate_client_rect(proposed, is_zoomed=True, work_area=work_area, autohide_edges=(False, False, False, True))
    assert res == (0, 0, 1920, 1079)


def test_calculate_client_rect_stale_qt_state_during_drag_restore():
    # Stale Qt state (thought it was maximized) vs real native state (is_zoomed=False)
    proposed = (400, 200, 1424, 787)
    work_area = (0, 0, 1920, 1040)
    # Native is_zoomed=False must NOT overwrite with work_area!
    res = calculate_client_rect(proposed, is_zoomed=False, work_area=work_area)
    assert res == proposed


def test_calculate_client_rect_secondary_monitor():
    proposed = (1920 - 8, -8, 3840 + 8, 1088)
    work_area = (1920, 0, 3840, 1040)
    res = calculate_client_rect(proposed, is_zoomed=True, work_area=work_area)
    assert res == (1920, 0, 3840, 1040)


def test_frameless_spike_smoke():
    import subprocess
    cmd = [sys.executable, "tools/frameless_spike.py", "--smoke"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# 2. Edge Grips integration tests
# ---------------------------------------------------------------------------

def test_edge_grips_placement_and_maximized(qtbot):
    win = QWidget()
    win.resize(1000, 700)
    qtbot.addWidget(win)
    win.show()

    grips = EdgeGrips(win)
    grips.update_geometry(1000, 700, is_maximized=False)

    # All 8 grips should not be hidden
    for g in grips.grips.values():
        assert not g.isHidden()

    # Geometry checks
    assert grips.grips[Region.TOPLEFT].geometry() == QRect(0, 0, CORNER_SIZE, CORNER_SIZE)
    assert grips.grips[Region.TOPRIGHT].geometry() == QRect(1000 - CORNER_SIZE, 0, CORNER_SIZE, CORNER_SIZE)
    assert grips.grips[Region.BOTTOMLEFT].geometry() == QRect(0, 700 - CORNER_SIZE, CORNER_SIZE, CORNER_SIZE)
    assert grips.grips[Region.BOTTOMRIGHT].geometry() == QRect(1000 - CORNER_SIZE, 700 - CORNER_SIZE, CORNER_SIZE, CORNER_SIZE)

    # Maximizing hides all grips
    grips.update_geometry(1000, 700, is_maximized=True)
    for g in grips.grips.values():
        assert g.isHidden()


def test_frame_controller_grips_mode(qtbot):
    win = QMainWindow()
    qtbot.addWidget(win)

    ctrl = FrameController(win)
    ctrl.native_mode = False  # force grips
    ctrl.on_show()

    assert ctrl.grips is not None
    assert len(ctrl.grips.grips) == 8

def test_hit_test_top_edge_fitts_law_over_caption_buttons():
    w, h = 1000, 700
    client_rects = [(950, 0, 50, 32)]  # Close button flush at top-right
    max_button_rect = (900, 0, 50, 32) # Maximize button flush at top edge

    # Topmost pixels (y = 1, 2) inside Close button must return CLIENT, not TOP or TOPRIGHT
    assert hit_test(975, 1, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.CLIENT
    assert hit_test(999, 1, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.CLIENT

    # Topmost pixels (y = 1, 2) inside Maximize button must return MAXBUTTON, not TOP
    assert hit_test(925, 1, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.MAXBUTTON

    # Normal top border away from buttons still returns TOP
    assert hit_test(500, 1, w, h, client_rects=client_rects, max_button_rect=max_button_rect) == Region.TOP


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 ctypes declarations only")
def test_win32_ctypes_argtypes_and_restype_declared():
    import ctypes
    from ctypes import wintypes
    import qt_ui.frameless as fl

    assert fl.user32.MonitorFromWindow.restype == wintypes.HMONITOR
    assert fl.user32.MonitorFromRect.restype == wintypes.HMONITOR
    assert fl.user32.GetMonitorInfoW.argtypes == [wintypes.HMONITOR, ctypes.c_void_p]
    assert fl.user32.GetMonitorInfoW.restype == wintypes.BOOL
    assert fl.shell32.SHAppBarMessage.restype == ctypes.c_size_t


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 autohide check only")
def test_get_autohide_taskbar_edges_secondary_monitor(monkeypatch):
    import ctypes
    from ctypes import wintypes
    import qt_ui.frameless as fl
    from qt_ui.frameless import NativeFrame, RECT

    class DummyWindow:
        pass

    nf = NativeFrame(DummyWindow())
    rc_mon = RECT(1920, 0, 3840, 1080)
    rc_work = RECT(1920, 0, 3840, 1080)

    def fake_shappbar(msg, p_data):
        if msg == fl.ABM_GETSTATE:
            return fl.ABS_AUTOHIDE
        return 0

    monkeypatch.setattr(fl.shell32, "SHAppBarMessage", fake_shappbar)
    edges = nf.get_autohide_taskbar_edges(hmon=123, rc_monitor=rc_mon, rc_work=rc_work)
    assert edges == (False, False, False, True)
