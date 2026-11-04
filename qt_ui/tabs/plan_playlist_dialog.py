"""Generic video details card and mode/provider helpers for PlanTab."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core import paths
from core.i18n import t
from core.palette import BG, BORDER, MUTED
from luckytwitch_engine import fmt_hms
from qt_ui.tabs.plan_crop_controls import CUT_HINT
from qt_ui.widgets import Card, ComboBox, Toggle


class PlanPlaylistMixin:
    """Mixin for PlanTab handling the generic video details card and provider routing."""

    def _build_generic_card(self) -> None:
        self.generic_card = Card(t("Video details"))
        self.generic_card.setVisible(False)
        self.body_layout.addWidget(self.generic_card)

        content_row = QWidget()
        c_lay = QHBoxLayout(content_row)
        c_lay.setContentsMargins(4, 4, 4, 4)
        c_lay.setSpacing(16)

        self.generic_thumb_label = QLabel()
        self.generic_thumb_label.setFixedSize(220, 124)
        self.generic_thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.generic_thumb_label.setStyleSheet(
            f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 6px; font-weight: bold; color: {MUTED};"
        )
        self.generic_thumb_label.setText(t("Video"))
        self.generic_thumb_label.setScaledContents(False)
        c_lay.addWidget(self.generic_thumb_label, 0, Qt.AlignmentFlag.AlignTop)

        right_col = QWidget()
        r_lay = QVBoxLayout(right_col)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(8)

        t_row = QWidget()
        t_lay = QHBoxLayout(t_row)
        t_lay.setContentsMargins(0, 0, 0, 0)
        t_lay.setSpacing(6)
        t_lbl = QLabel(t("Title:"))
        t_lbl.setProperty("role", "muted")
        t_lay.addWidget(t_lbl)

        self.generic_title_entry = QLineEdit()
        self.generic_title_entry.setPlaceholderText(t("Video title…"))
        self.generic_title_entry.textChanged.connect(self._on_generic_title_edited)
        t_lay.addWidget(self.generic_title_entry, 1)

        self.generic_reset_title_btn = QPushButton(t("Reset"))
        self.generic_reset_title_btn.setProperty("variant", "ghost")
        self.generic_reset_title_btn.clicked.connect(self.reset_title)
        t_lay.addWidget(self.generic_reset_title_btn)
        r_lay.addWidget(t_row)

        meta_row = QWidget()
        m_lay = QHBoxLayout(meta_row)
        m_lay.setContentsMargins(0, 0, 0, 0)
        m_lay.setSpacing(12)

        self.generic_uploader_lbl = QLabel("")
        self.generic_uploader_lbl.setProperty("role", "muted")
        m_lay.addWidget(self.generic_uploader_lbl)

        self.generic_duration_lbl = QLabel("")
        self.generic_duration_lbl.setProperty("role", "muted")
        m_lay.addWidget(self.generic_duration_lbl)

        self.generic_date_lbl = QLabel("")
        self.generic_date_lbl.setProperty("role", "muted")
        m_lay.addWidget(self.generic_date_lbl)
        m_lay.addStretch(1)
        r_lay.addWidget(meta_row)

        r_lay.addSpacing(4)

        opts_grid = QGridLayout()
        opts_grid.setContentsMargins(0, 0, 0, 0)
        opts_grid.setHorizontalSpacing(10)
        opts_grid.setVerticalSpacing(8)

        q_lbl = QLabel(t("Quality:"))
        q_lbl.setProperty("role", "muted")
        opts_grid.addWidget(q_lbl, 0, 0)

        self.generic_quality_combo = ComboBox()
        self.generic_quality_combo.activated.connect(self._on_generic_quality_activated)
        opts_grid.addWidget(self.generic_quality_combo, 0, 1)

        c_lbl = QLabel(t("Format:"))
        c_lbl.setProperty("role", "muted")
        opts_grid.addWidget(c_lbl, 0, 2)

        self.generic_container_combo = ComboBox()
        for c in ("mp4", "mkv", "mp3", "m4a"):
            self.generic_container_combo.addItem(c, c)
        opts_grid.addWidget(self.generic_container_combo, 0, 3)

        self.generic_audio_toggle = Toggle()
        self.generic_audio_toggle.clicked.connect(self._on_generic_audio_toggled)
        audio_box = QWidget()
        ab_lay = QHBoxLayout(audio_box)
        ab_lay.setContentsMargins(0, 0, 0, 0)
        ab_lay.setSpacing(6)
        ab_lay.addWidget(QLabel(t("Audio only")))
        ab_lay.addWidget(self.generic_audio_toggle)
        opts_grid.addWidget(audio_box, 0, 4)

        self.generic_cookies_toggle = Toggle()
        self.generic_cookies_box = QWidget()
        cb_lay = QHBoxLayout(self.generic_cookies_box)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        cb_lay.setSpacing(6)
        self.generic_cookies_label = QLabel(t("Cookies"))
        cb_lay.addWidget(self.generic_cookies_label)
        cb_lay.addWidget(self.generic_cookies_toggle)
        opts_grid.addWidget(self.generic_cookies_box, 0, 5)

        f_lbl = QLabel(t("Folder:"))
        f_lbl.setProperty("role", "muted")
        opts_grid.addWidget(f_lbl, 1, 0)

        self.generic_folder_entry = QLineEdit()
        self.generic_folder_entry.setText(str(self.settings.get("out_dir", getattr(paths, "DOWNLOADS_DIR", ""))))
        opts_grid.addWidget(self.generic_folder_entry, 1, 1, 1, 4)

        self.generic_browse_btn = QPushButton(t("Browse…"))
        self.generic_browse_btn.setProperty("variant", "ghost")
        self.generic_browse_btn.clicked.connect(self._browse_generic_folder)
        opts_grid.addWidget(self.generic_browse_btn, 1, 5)

        r_lay.addLayout(opts_grid)
        c_lay.addWidget(right_col, 1)
        self.generic_card.add_widget(content_row)

    def _on_generic_title_edited(self, text: str) -> None:
        clean = text.strip()
        if self.source:
            self.source.title = clean
        self.title_changed.emit(clean)

    def _on_generic_audio_toggled(self) -> None:
        is_audio = self.generic_audio_toggle.isChecked()
        current = self.generic_container_combo.currentText().lower()
        if is_audio and current in ("mp4", "mkv"):
            self.generic_container_combo.setCurrentText("mp3")
        elif not is_audio and current in ("mp3", "m4a"):
            self.generic_container_combo.setCurrentText("mp4")
        self.update_preview()

    def _browse_generic_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        initial = self.generic_folder_entry.text().strip() or str(getattr(paths, "DOWNLOADS_DIR", ""))
        d = QFileDialog.getExistingDirectory(self, t("Select download folder"), initial)
        if d:
            self.generic_folder_entry.setText(d)

    def _on_generic_quality_activated(self, _index: int = 0) -> None:
        data = self.generic_quality_combo.currentData()
        for i in range(self.quality_combo.count()):
            if self.quality_combo.itemData(i) == data:
                self.quality_combo.setCurrentIndex(i)
                break
        self.update_preview()
        self.quality_changed.emit(self.current_quality())

    def set_mode(self, has_timeline: bool) -> None:
        self.mode_timeline = bool(has_timeline)
        self.timeline_card.setVisible(self.mode_timeline)
        self.cuts_card.setVisible(True)
        self.title_row.setVisible(self.mode_timeline)
        self.quality_row.setVisible(self.mode_timeline and bool(getattr(self.source, "formats", None)))
        self.clips_card.setVisible(self.mode_timeline)
        self.generic_card.setVisible(not self.mode_timeline)
        if not self.mode_timeline:
            self.onboarding_card.setVisible(False)
            self.cuts_hint.setText(
                t("Optional: write cut points to trim or split (e.g. 1:00 - 5:00 ; 12:00 - end). Leave blank for full video.")
            )
        else:
            self.cuts_hint.setText(t(CUT_HINT))
        self.update_preview()

    def update_generic_card(self, source) -> None:
        if source is None:
            return
        self.generic_title_entry.setText(source.title or "")
        site_str = getattr(source, "site", "video") or "video"
        uploader = source.uploader or site_str.capitalize()
        self.generic_uploader_lbl.setText(f"{uploader}")
        self.generic_duration_lbl.setText(f"{fmt_hms(source.duration)}")
        self.generic_date_lbl.setText(f"{source.date or ''}")

        self.generic_thumb_label.setPixmap(QPixmap())
        self.generic_thumb_label.setText(site_str.upper()[:4])
        thumb_url = getattr(source, "thumbnail", "")
        if thumb_url:
            self._fetch_generic_thumbnail(thumb_url)

        browser = str(self.settings.get("cookies_from_browser", "None")).strip()
        has_browser = browser.lower() not in ("none", "disabled", "")
        if has_browser and hasattr(self, "generic_cookies_box"):
            self.generic_cookies_box.setVisible(True)
            self.generic_cookies_label.setText(t("Cookies ({browser})", browser=browser))
            self.generic_cookies_box.setToolTip(t("Send cookies from {browser} for this download", browser=browser))
            from core.cookie_scope import is_cookie_eligible
            scope = str(self.settings.get("cookies_scope", "known_only"))
            eligible = is_cookie_eligible(getattr(source, "url", ""), scope_mode=scope)
            self.generic_cookies_toggle.setChecked(eligible)
        elif hasattr(self, "generic_cookies_box"):
            self.generic_cookies_box.setVisible(False)
            self.generic_cookies_toggle.setChecked(False)

        if hasattr(self, "generic_folder_entry"):
            from core.routing import resolve_provider_base_dir
            base_dir = self.settings.get("out_dir", getattr(paths, "DOWNLOADS_DIR", ""))
            provider_subfolders = bool(self.settings.get("provider_subfolders", False))
            provider_out_dirs = self.settings.get("provider_out_dirs") or {}
            resolved_dir = resolve_provider_base_dir(
                base_dir,
                site_or_provider=site_str,
                provider_subfolders=provider_subfolders,
                provider_out_dirs=provider_out_dirs,
            )
            self.generic_folder_entry.setText(str(resolved_dir))

    def _fetch_generic_thumbnail(self, url: str) -> None:
        self._expected_thumb_url = url

        def work():
            try:
                from luckytwitch_engine import fetch_thumbnail
                p = fetch_thumbnail(url)
                if p and Path(p).is_file():
                    self.generic_thumb_loaded.emit(f"{url}:::{p}")
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_generic_thumb_file(self, payload: str) -> None:
        if ":::" in payload:
            url, path_str = payload.split(":::", 1)
        else:
            url, path_str = "", payload
        if url and url != getattr(self, "_expected_thumb_url", None):
            return
        pm = QPixmap(path_str)
        if not pm.isNull():
            scaled = pm.scaled(
                self.generic_thumb_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.generic_thumb_label.setPixmap(scaled)
            self.generic_thumb_label.setText("")

    def card_title(self) -> str:
        if not getattr(self, "mode_timeline", True):
            return self.generic_title_entry.text().strip()
        return self.title_entry.text().strip()

    def current_container(self) -> str:
        if hasattr(self, "generic_container_combo"):
            return self.generic_container_combo.currentText()
        return "mp4"

    def is_audio_only(self) -> bool:
        if hasattr(self, "generic_audio_toggle"):
            return self.generic_audio_toggle.isChecked()
        return False

    def is_cookies_enabled(self) -> bool:
        if hasattr(self, "generic_cookies_toggle") and hasattr(self, "generic_cookies_box"):
            return not self.generic_cookies_box.isHidden() and self.generic_cookies_toggle.isChecked()
        return False

    def current_output_dir(self) -> str:
        if hasattr(self, "generic_folder_entry"):
            return self.generic_folder_entry.text().strip()
        return ""
