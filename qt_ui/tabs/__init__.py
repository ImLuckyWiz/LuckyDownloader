"""The four tabs of the main window. Empty in Phase 1; each later phase fills one in."""

from qt_ui.tabs.options import OptionsTab
from qt_ui.tabs.plan import PlanTab
from qt_ui.tabs.queue import QueueTab
from qt_ui.tabs.search import BrowseTab, SearchTab

__all__ = ["BrowseTab", "SearchTab", "PlanTab", "OptionsTab", "QueueTab"]
