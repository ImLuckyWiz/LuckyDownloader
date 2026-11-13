"""Models and the thumbnail painting of the Search tab (decision D5).

``ChannelModel``  a list of streamers (the search results, the recent streamers). The row text is the name, with
                  «● » in front of a streamer who is live (results only).
``VodModel``      the VOD table: thumbnail, title, date, length, views. One row per VOD; ``append`` adds a page.
``ThumbCache``    QPixmaps of the thumbnails, size-capped (least recently used goes first). Built on the GUI
                  thread only. A row whose pixmap was dropped is rebuilt from its file when it is painted again.
``ThumbDelegate`` paints the thumbnail column.

Nothing here touches the network. QPixmap is created on the GUI thread only (the rule of PLAN.md section 1).
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPen, QPixmap
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from core.i18n import N_, t, tn
from core.search import THUMB_GAP, THUMB_SIZE
from luckytwitch_engine import fmt_hms

CHANNEL_ROLE = Qt.ItemDataRole.UserRole + 1  # the streamer dict of a row: {id, login, name, live}
AVATAR_ROLE = Qt.ItemDataRole.UserRole + 2  # QPixmap of streamer avatar (or None)
FAVORITE_ROLE = Qt.ItemDataRole.UserRole + 3  # bool: whether the streamer is in Favorites
VIDEO_ROLE = Qt.ItemDataRole.UserRole + 1  # the VOD dict of a row
THUMB_ROLE = Qt.ItemDataRole.UserRole + 2  # the QPixmap of a row (or None)
THUMB_MARGIN = 6  # space to the left of a thumbnail
THUMB_COLUMN_WIDTH = THUMB_MARGIN + THUMB_SIZE[0] + THUMB_GAP
ROW_HEIGHT = THUMB_SIZE[1] + 8  # tall rows: room for the thumbnails
CHANNEL_ROW_HEIGHT = 36
MAX_CACHED_THUMBS = 300

VOD_COLUMNS = (  # key, heading, width, alignment, stretches
    ("thumb", "", THUMB_COLUMN_WIDTH, "w", False),
    ("title", N_("Title"), 360, "w", True),
    ("date", N_("Date"), 90, "center", False),
    ("dur", N_("Length"), 80, "center", False),
    ("views", N_("Views"), 70, "center", False),
)


def _alignment(kind: str) -> Qt.AlignmentFlag:
    return (Qt.AlignmentFlag.AlignHCenter if kind == "center" else Qt.AlignmentFlag.AlignLeft) | \
        Qt.AlignmentFlag.AlignVCenter


def load_thumb(path: str) -> QPixmap | None:
    """The file as a pixmap of exactly ``THUMB_SIZE`` (stretched like the tkinter ``resize``), or None when it
    cannot be read. GUI thread only."""
    image = QImage(path)
    if image.isNull():
        return None
    pix = QPixmap.fromImage(image.scaled(THUMB_SIZE[0], THUMB_SIZE[1], Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
    return None if pix.isNull() else pix


def load_avatar(path: str, size: int = 48) -> QPixmap | None:
    """The file as an avatar pixmap (square, high-DPI ready), or None when unreadable. GUI thread only."""
    image = QImage(path)
    if image.isNull():
        return None
    pix = QPixmap.fromImage(image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                         Qt.TransformationMode.SmoothTransformation))
    return None if pix.isNull() else pix


class ThumbCache:
    """Row id -> QPixmap, at most ``limit`` of them; the least recently used is dropped first."""

    def __init__(self, limit: int = MAX_CACHED_THUMBS):
        self.limit = limit
        self._pix: OrderedDict[str, QPixmap] = OrderedDict()

    def __len__(self) -> int:
        return len(self._pix)

    def __contains__(self, iid: str) -> bool:
        return iid in self._pix

    def put(self, iid: str, pix: QPixmap) -> None:
        self._pix[iid] = pix
        self._pix.move_to_end(iid)
        while len(self._pix) > self.limit:
            self._pix.popitem(last=False)

    def get(self, iid: str) -> QPixmap | None:
        pix = self._pix.get(iid)
        if pix is not None:
            self._pix.move_to_end(iid)
        return pix

    def clear(self) -> None:
        self._pix.clear()


class ChannelModel(QAbstractListModel):
    """Streamers as a list. ``live_marker=True`` (the search results) puts «● » before a live streamer."""

    def __init__(self, live_marker: bool = False, parent=None):
        super().__init__(parent)
        self.live_marker = live_marker
        self.channels: list[dict] = []
        self._avatars: dict[str, QPixmap] = {}
        self._favorite_ids: set[str] = set()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.channels)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.channels):
            return None
        ch = self.channels[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return ("● " if self.live_marker and ch.get("live") else "") + str(ch.get("name", ""))
        if role == CHANNEL_ROLE:
            return ch
        if role == AVATAR_ROLE:
            cid = str(ch.get("id") or "")
            return self._avatars.get(cid)
        if role == FAVORITE_ROLE:
            cid = str(ch.get("id") or "")
            return cid in self._favorite_ids
        return None

    def set_channels(self, channels: list[dict]) -> None:
        self.beginResetModel()
        self.channels = list(channels)
        self.endResetModel()

    def set_favorite_ids(self, ids: set[str]) -> None:
        self._favorite_ids = set(ids)
        if self.channels:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.channels) - 1, 0), [FAVORITE_ROLE])

    def has_avatar(self, channel_id: str) -> bool:
        return str(channel_id) in self._avatars

    def set_avatar(self, channel_id: str, pix: QPixmap) -> None:
        cid = str(channel_id)
        self._avatars[cid] = pix
        for row, ch in enumerate(self.channels):
            if str(ch.get("id")) == cid:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [AVATAR_ROLE])


class VodModel(QAbstractTableModel):
    """The VODs of the picked streamer. ``cache`` holds the thumbnails; ``paths`` the file each row's thumbnail
    was fetched to (so a pixmap the cache dropped can be made again)."""

    def __init__(self, cache: ThumbCache | None = None, parent=None):
        super().__init__(parent)
        self.cache = cache if cache is not None else ThumbCache()
        self.videos: list[dict] = []
        self.paths: dict[str, str] = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.videos)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(VOD_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(VOD_COLUMNS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            col_label = VOD_COLUMNS[section][1]
            return t(col_label) if col_label else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:  # the heading lines up with its column
            return int(_alignment(VOD_COLUMNS[section][3]))
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.videos):
            return None
        v, col = self.videos[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return ("", v["title"], v["date"], fmt_hms(v["duration"]), str(v["views"]))[col]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(_alignment(VOD_COLUMNS[col][3]))
        if role == VIDEO_ROLE:
            return v
        if role == THUMB_ROLE:
            return self.pixmap(str(index.row())) if col == 0 else None
        return None

    def pixmap(self, iid: str) -> QPixmap | None:
        """The thumbnail of row ``iid``: from the cache, or made again from its file (GUI thread)."""
        pix = self.cache.get(iid)
        if pix is None and iid in self.paths:
            pix = load_thumb(self.paths[iid])
            if pix is not None:
                self.cache.put(iid, pix)
        return pix

    def clear(self) -> None:
        self.beginResetModel()
        self.videos, self.paths = [], {}
        self.cache.clear()
        self.endResetModel()

    def refresh_language(self) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(VOD_COLUMNS) - 1)

    def append(self, videos: list[dict]) -> int:
        """Add a page; returns the row number of its first row (the row id of a VOD is its row number)."""
        start = len(self.videos)
        if videos:
            self.beginInsertRows(QModelIndex(), start, start + len(videos) - 1)
            self.videos.extend(videos)
            self.endInsertRows()
        return start

    def set_thumb(self, iid: str, path: str) -> bool:
        """A thumbnail arrived for row ``iid``. False when the row is gone or the file is not an image."""
        if not iid.isdigit() or int(iid) >= len(self.videos):
            return False
        pix = load_thumb(path)
        if pix is None:
            return False  # unreadable image: the row simply has none
        self.paths[iid] = path
        self.cache.put(iid, pix)
        index = self.index(int(iid), 0)
        self.dataChanged.emit(index, index, [THUMB_ROLE])
        return True


class ThumbDelegate(QStyledItemDelegate):
    """Paints the thumbnail column: the selection colour behind, the picture on the left, vertically centred."""

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        pix = index.data(THUMB_ROLE)
        box = QRect(option.rect.left() + THUMB_MARGIN, option.rect.top() + (option.rect.height() - THUMB_SIZE[1]) // 2,
                    THUMB_SIZE[0], THUMB_SIZE[1])
        if pix is not None:
            painter.drawPixmap(box, pix)
        else:
            from PySide6.QtGui import QColor
            from core.palette import BG3
            painter.setRenderHint(painter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG3))
            painter.drawRoundedRect(box, 4, 4)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(THUMB_COLUMN_WIDTH, ROW_HEIGHT)


GRID_CARD_W = 220
GRID_CARD_H = 192
GRID_THUMB_W = 204
GRID_THUMB_H = 115


class VodGridDelegate(QStyledItemDelegate):
    """Paints a VOD card in Grid mode (C2, C3): 16:9 thumbnail (or skeleton tile), duration badge, 2-line title,
    and ``date · views`` subtitle."""

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPen
        from core.palette import ACCENT, ACCENT_DIM, ACCENT_HOVER, BG, BG2, BG3, BORDER, FG, MUTED, WHITE

        v = index.data(VIDEO_ROLE) or {}
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        lift = -2.0 if hovered else 0.0
        card = QRectF(option.rect).adjusted(4.0, 4.0 + lift, -4.0, -4.0 + lift)

        bg_col = QColor(ACCENT_DIM if selected else (BG3 if hovered else BG2))
        border_col = QColor(ACCENT if selected else (ACCENT_HOVER if hovered else BORDER))
        painter.setPen(QPen(border_col, 1.5 if selected else 1.0))
        painter.setBrush(bg_col)
        painter.drawRoundedRect(card, 8.0, 8.0)

        thumb_rect = QRectF(card.left() + 8.0, card.top() + 8.0, card.width() - 16.0, GRID_THUMB_H)
        model = index.model()
        row_idx = index.row()
        pix = model.index(row_idx, 0).data(THUMB_ROLE) if model is not None else None
        if pix is not None and not pix.isNull():
            scaled = pix.scaled(int(thumb_rect.width()), int(thumb_rect.height()),
                                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(thumb_rect.topLeft().toPoint(), scaled)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG3))
            painter.drawRoundedRect(thumb_rect, 4.0, 4.0)

        dur_txt = fmt_hms(v.get("duration", 0))
        font_badge = QFont(option.font)
        font_badge.setPointSize(8)
        font_badge.setBold(True)
        painter.setFont(font_badge)
        fm_badge = painter.fontMetrics()
        bw = fm_badge.horizontalAdvance(dur_txt) + 10.0
        bh = 18.0
        badge_rect = QRectF(thumb_rect.right() - bw - 4.0, thumb_rect.bottom() - bh - 4.0, bw, bh)
        pill_bg = QColor(BG)
        pill_bg.setAlpha(220)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pill_bg)
        painter.drawRoundedRect(badge_rect, 4.0, 4.0)
        painter.setPen(QColor(WHITE))
        painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), dur_txt)

        vod_id = str(v.get("id", ""))
        from core import history
        if history.is_downloaded(vod_id):
            dl_font = QFont(option.font)
            dl_font.setPointSize(7)
            dl_font.setBold(True)
            painter.setFont(dl_font)
            dl_fm = painter.fontMetrics()
            dl_txt = t("✓ Downloaded")
            dl_w = dl_fm.horizontalAdvance(dl_txt) + 8.0
            dl_rect = QRectF(thumb_rect.left() + 4.0, thumb_rect.top() + 4.0, dl_w, 16.0)
            from core.palette import OK
            dl_bg = QColor(OK)
            dl_bg.setAlpha(220)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dl_bg)
            painter.drawRoundedRect(dl_rect, 3.0, 3.0)
            painter.setPen(QColor(WHITE))
            painter.drawText(dl_rect, int(Qt.AlignmentFlag.AlignCenter), dl_txt)

        title = str(v.get("title") or "")
        font_title = QFont(option.font)
        font_title.setPointSize(9)
        font_title.setBold(True)
        painter.setFont(font_title)
        painter.setPen(QColor(FG))
        title_rect = QRectF(thumb_rect.left(), thumb_rect.bottom() + 6.0, thumb_rect.width(), 34.0)
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                         painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, int(title_rect.width() * 1.9)))

        from qt_ui import i18n_qt
        raw_date = v.get("date", "")
        date_str = i18n_qt.format_date(raw_date) if raw_date else ""
        views_cnt = int(v.get("views", 0) or 0)
        views_str = tn("{n} view", "{n} views", views_cnt)
        meta = f"{date_str}  ·  {views_str}" if date_str else views_str
        font_meta = QFont(option.font)
        font_meta.setPointSize(8)
        painter.setFont(font_meta)
        painter.setPen(QColor(MUTED))
        meta_rect = QRectF(thumb_rect.left(), card.bottom() - 20.0, thumb_rect.width(), 16.0)
        painter.drawText(meta_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), meta)

        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(GRID_CARD_W, GRID_CARD_H)



def channel_avatar_colour(name: str) -> str:
    """Deterministic vibrant hue for a streamer avatar background."""
    import zlib
    from core.timeline import GAME_COLOURS
    h = zlib.crc32(name.strip().lower().encode("utf-8"))
    return GAME_COLOURS[h % len(GAME_COLOURS)]


class ChannelDelegate(QStyledItemDelegate):
    """Paints streamer list rows: avatar initials circle, display name, red LIVE badge (C1, C5), and optional favorite/remove buttons."""

    def __init__(self, live_marker: bool = False, removable: bool = False, favoritable: bool = False, parent=None):
        super().__init__(parent)
        self.live_marker = live_marker
        self.removable = removable
        self.favoritable = favoritable
        self._hover_pos: QPoint | None = None

    def set_hover_pos(self, pos: QPoint | None) -> None:
        self._hover_pos = pos

    @staticmethod
    def remove_button_rect(rect: QRect) -> QRectF:
        size = 20.0
        bx = rect.right() - size - 6.0
        by = rect.top() + (rect.height() - size) / 2.0
        return QRectF(bx, by, size, size)

    def favorite_button_rect(self, rect: QRect, is_live: bool = False) -> QRectF:
        size = 20.0
        by = rect.top() + (rect.height() - size) / 2.0
        if self.removable:
            bx = rect.right() - size - 6.0 - size - 2.0
        elif self.live_marker and is_live:
            bx = rect.right() - 38.0 - 6.0 - size - 4.0
        else:
            bx = rect.right() - size - 6.0
        return QRectF(bx, by, size, size)

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        from PySide6.QtGui import QColor, QFont
        from core.palette import BG2, ERR, FG, HOVER, MUTED, WHITE

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.fillRect(rect, option.palette.highlight())
        elif hovered:
            painter.fillRect(rect, QColor(BG2))

        ch = index.data(CHANNEL_ROLE) or {}
        raw_name = str(ch.get("name") or ch.get("login") or index.data(Qt.ItemDataRole.DisplayRole) or "")
        clean_name = raw_name[2:] if raw_name.startswith("● ") else raw_name
        is_live = bool(ch.get("live", False)) or raw_name.startswith("● ")

        # Avatar circle
        size = 24.0
        pad_x = 8.0
        cy = rect.top() + (rect.height() - size) / 2.0
        avatar_rect = QRectF(rect.left() + pad_x, cy, size, size)

        pix = index.data(AVATAR_ROLE)
        if pix is not None and not pix.isNull():
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.addEllipse(avatar_rect)
            painter.save()
            painter.setClipPath(path)
            scaled = pix.scaled(int(avatar_rect.width()), int(avatar_rect.height()),
                                Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(avatar_rect.topLeft().toPoint(), scaled)
            painter.restore()
        else:
            col = QColor(channel_avatar_colour(clean_name))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawEllipse(avatar_rect)

            initial = (clean_name[:1] or "?").upper()
            font_init = QFont(option.font)
            font_init.setPointSize(10)
            font_init.setBold(True)
            painter.setFont(font_init)
            painter.setPen(QColor(WHITE))
            painter.drawText(avatar_rect, int(Qt.AlignmentFlag.AlignCenter), initial)

        is_fav = bool(index.data(FAVORITE_ROLE))
        show_fav = self.favoritable and (hovered or is_fav)
        show_rem = self.removable and hovered

        # Streamer name
        name_x = rect.left() + pad_x + size + 8.0
        avail_w = rect.width() - (name_x - rect.left()) - 6.0
        if is_live and self.live_marker:
            avail_w -= 46.0 + (24.0 if show_fav else 0.0)
        elif show_rem and show_fav:
            avail_w -= 48.0
        elif show_rem or show_fav:
            avail_w -= 26.0

        font_name = QFont(option.font)
        font_name.setPointSize(10)
        painter.setFont(font_name)
        text_col = option.palette.highlightedText().color() if selected else QColor(FG)
        painter.setPen(text_col)
        name_rect = QRectF(name_x, rect.top(), max(avail_w, 10.0), rect.height())
        fm = painter.fontMetrics()
        elided = fm.elidedText(clean_name, Qt.TextElideMode.ElideRight, int(name_rect.width()))
        painter.drawText(name_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), elided)

        # Red LIVE badge (C5)
        if is_live and self.live_marker:
            badge_w, badge_h = 38.0, 16.0
            bx = rect.right() - badge_w - 6.0
            by = rect.top() + (rect.height() - badge_h) / 2.0
            badge_rect = QRectF(bx, by, badge_w, badge_h)

            from qt_ui.motion import Motion
            if Motion.enabled():
                import time, math
                alpha = int(195 + 60 * math.sin(time.time() * 3.5))
                col = QColor(235, 4, 0, max(120, min(255, alpha)))
            else:
                col = QColor("#eb0400")

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawRoundedRect(badge_rect, 3.0, 3.0)

            font_live = QFont(option.font)
            font_live.setPointSize(7)
            font_live.setBold(True)
            painter.setFont(font_live)
            painter.setPen(QColor(WHITE))
            painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), "LIVE")

        # Heart button (always shown when favorited; shown on hover otherwise)
        if show_fav:
            fav_rect = self.favorite_button_rect(rect, is_live=is_live)
            fav_hovered = self._hover_pos is not None and fav_rect.contains(QPointF(self._hover_pos))
            if fav_hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(HOVER))
                painter.drawRoundedRect(fav_rect, 4.0, 4.0)
                heart_col = ERR
            elif is_fav:
                heart_col = ERR
            else:
                heart_col = option.palette.highlightedText().color().name() if selected else MUTED
            from qt_ui.icons import pixmap as icon_pixmap
            dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
            hpix = icon_pixmap("heart-filled" if is_fav else "heart", 14, heart_col, dpr=dpr)
            hx = fav_rect.center().x() - 7.0
            hy = fav_rect.center().y() - 7.0
            painter.drawPixmap(QPointF(hx, hy), hpix)

        # Hover remove ('x') button for recent items
        if show_rem:
            btn_rect = self.remove_button_rect(rect)
            btn_hovered = self._hover_pos is not None and btn_rect.contains(QPointF(self._hover_pos))
            if btn_hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(HOVER))
                painter.drawRoundedRect(btn_rect, 4.0, 4.0)
                x_col = QColor(ERR)
            else:
                x_col = option.palette.highlightedText().color() if selected else QColor(MUTED)
            painter.setPen(QPen(x_col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            cx, cy = btn_rect.center().x(), btn_rect.center().y()
            r = 4.0
            painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            painter.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, CHANNEL_ROW_HEIGHT)
