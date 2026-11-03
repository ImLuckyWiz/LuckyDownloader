"""Window and UI state persistence (geometry, active tab, panel states).

Stored separately in ``luckytwitch_ui.json`` so saved job settings (``luckytwitch_settings.json``)
are never polluted with ephemeral layout state.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core import paths


@dataclass
class UIState:
    window_x: int | None = None
    window_y: int | None = None
    window_w: int = 1020
    window_h: int = 910
    active_tab: str = "Plan"
    rail_expanded: bool = False
    log_open: bool = False
    splitter_sizes: list[int] | None = None
    has_completed_onboarding: bool = False
    window_maximized: bool = False
    custom_titlebar: bool = True
    max_concurrent_jobs: int = 1
    rate_limit: str = ""
    language: str = "auto"  # "auto" (follow the system), "en" or "es"


DEFAULT_UI_STATE = UIState()


def load_ui_state(path: Path | None = None) -> UIState:
    """Read the UI state from disk. Returns defaults if missing or corrupted."""
    target = path or getattr(paths, "UI_STATE_PATH", paths.DATA_DIR / "luckytwitch_ui.json")
    try:
        if target.is_file():
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return UIState(
                    window_x=data.get("window_x"),
                    window_y=data.get("window_y"),
                    window_w=int(data.get("window_w", 1020)),
                    window_h=int(data.get("window_h", 910)),
                    active_tab=str(data.get("active_tab", "Plan")),
                    rail_expanded=bool(data.get("rail_expanded", False)),
                    log_open=bool(data.get("log_open", False)),
                    splitter_sizes=data.get("splitter_sizes"),
                    has_completed_onboarding=bool(data.get("has_completed_onboarding", False)),
                    window_maximized=bool(data.get('window_maximized', False)),
                    custom_titlebar=bool(data.get('custom_titlebar', True)),
                    max_concurrent_jobs=int(data.get('max_concurrent_jobs', 1)),
                    rate_limit=str(data.get('rate_limit', '')),
                    language=str(data.get('language', 'auto')),
                )
    except Exception:  # noqa: BLE001
        pass
    return UIState()


def save_ui_state(state: UIState | dict[str, Any], path: Path | None = None) -> None:
    """Write the UI state to disk safely. Never raises."""
    target = path or getattr(paths, "UI_STATE_PATH", paths.DATA_DIR / "luckytwitch_ui.json")
    try:
        data = asdict(state) if isinstance(state, UIState) else dict(state)
        from core.files import atomic_write_json
        atomic_write_json(target, data)
    except Exception:  # noqa: BLE001
        pass
