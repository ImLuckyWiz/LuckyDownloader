"""
LuckyDownloader engine facade.

Re-exports all symbols from `luckytwitch_engine` and `core/` for the modern LuckyDownloader naming.
"""

from __future__ import annotations

import sys as _sys
import luckytwitch_engine as _eng

_sys.modules[__name__] = _eng
