import json
import re
import sys
import unicodedata
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal, QRect, QTimer
from PySide6.QtGui import QPixmap, QAction, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def natural_key(path: Path):
    name = unicodedata.normalize("NFKC", path.stem).casefold()
    parts = re.split(r"(\d+)", name)

    key = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)

    key.append(path.suffix.casefold())
    return key


class AspectImageLabel(QLabel):
    wheel_up = Signal()
    wheel_down = Signal()
    ctrl_wheel_up = Signal()
    ctrl_wheel_down = Signal()
    context_menu_requested = Signal(object)

    def __init__(self, empty_text="", target_ratio=None, parent=None):
        super().__init__(parent)
        self.empty_text = empty_text
        self.target_ratio = target_ratio

        self._base_pixmap = None
        self._underlay_pixmap = None
        self._overlay_bottom_pixmap = None
        self._overlay_middle_pixmap = None
        self._overlay_top_pixmap = None
        self._zoom_factor = 1.0

        self.setAlignment(Qt.AlignCenter)
        self.setText(self.empty_text)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("""
            QLabel {
                background: #1e1e1e;
                color: #cfcfcf;
                border: 1px solid #444444;
            }
        """)

    def set_image(self, image_path: str | None):
        if not image_path:
            self._base_pixmap = None
            self.setPixmap(QPixmap())
            self.setText(self.empty_text)
            return

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self._base_pixmap = None
            self.setPixmap(QPixmap())
            self.setText("画像の読み込みに失敗しました")
            return

        self._base_pixmap = pixmap
        self._update_scaled_pixmap()

    def set_underlay(self, underlay_path: str | None):
        if not underlay_path:
            self._underlay_pixmap = None
            self._update_scaled_pixmap()
            return

        pixmap = QPixmap(underlay_path)
        if pixmap.isNull():
            self._underlay_pixmap = None
            self._update_scaled_pixmap()
            return

        self._underlay_pixmap = pixmap
        self._update_scaled_pixmap()

    def set_overlay_bottom(self, overlay_path: str | None):
        self._overlay_bottom_pixmap = self._load_optional_pixmap(overlay_path)
        self._update_scaled_pixmap()

    def set_overlay_middle(self, overlay_path: str | None):
        self._overlay_middle_pixmap = self._load_optional_pixmap(overlay_path)
        self._update_scaled_pixmap()

    def set_overlay_top(self, overlay_path: str | None):
        self._overlay_top_pixmap = self._load_optional_pixmap(overlay_path)
        self._update_scaled_pixmap()

    def _load_optional_pixmap(self, image_path: str | None):
        if not image_path:
            return None
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return None
        return pixmap

    def set_target_ratio(self, ratio: float | None):
        self.target_ratio = ratio
        self._update_scaled_pixmap()

    def set_zoom_factor(self, zoom_factor: float):
        self._zoom_factor = max(0.1, zoom_factor)
        self._update_scaled_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        modifiers = QApplication.keyboardModifiers()

        if modifiers & Qt.ControlModifier:
            if delta > 0:
                self.ctrl_wheel_up.emit()
            elif delta < 0:
                self.ctrl_wheel_down.emit()
            event.accept()
            return

        if delta > 0:
            self.wheel_up.emit()
        elif delta < 0:
            self.wheel_down.emit()
        event.accept()

    def contextMenuEvent(self, event):
        self.context_menu_requested.emit(event.globalPos())
        event.accept()

    def _calc_draw_rect(self, src_w: int, src_h: int):
        area_w = max(1, self.width())
        area_h = max(1, self.height())

        if self.target_ratio:
            area_ratio = area_w / area_h
            if area_ratio > self.target_ratio:
                box_h = area_h
                box_w = int(box_h * self.target_ratio)
            else:
                box_w = area_w
                box_h = int(box_w / self.target_ratio)
        else:
            box_w, box_h = area_w, area_h

        box_w = max(1, int(box_w * self._zoom_factor))
        box_h = max(1, int(box_h * self._zoom_factor))

        img_ratio = src_w / src_h
        box_ratio = box_w / box_h

        if img_ratio > box_ratio:
            draw_w = box_w
            draw_h = int(draw_w / img_ratio)
        else:
            draw_h = box_h
            draw_w = int(draw_h * img_ratio)

        offset_x = (area_w - draw_w) // 2
        offset_y = (area_h - draw_h) // 2

        return QRect(offset_x, offset_y, draw_w, draw_h)

    def _draw_scaled_pixmap(self, painter: QPainter, pixmap: QPixmap | None, rect: QRect):
        if pixmap is None:
            return
        scaled = pixmap.scaled(
            rect.size(),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation
        )
        painter.drawPixmap(rect.topLeft(), scaled)

    def _update_scaled_pixmap(self):
        if self._base_pixmap is None:
            self.setPixmap(QPixmap())
            if self.text() == "":
                self.setText(self.empty_text)
            return

        area_w = max(1, self.width())
        area_h = max(1, self.height())

        canvas = QPixmap(area_w, area_h)
        canvas.fill(Qt.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        base_rect = self._calc_draw_rect(
            self._base_pixmap.width(),
            self._base_pixmap.height()
        )

        # 1. 背景
        self._draw_scaled_pixmap(painter, self._underlay_pixmap, base_rect)

        # 2. メイン
        painter.drawPixmap(base_rect, self._base_pixmap)

        # 3. 固定3スロット
        self._draw_scaled_pixmap(painter, self._overlay_bottom_pixmap, base_rect)
        self._draw_scaled_pixmap(painter, self._overlay_middle_pixmap, base_rect)
        self._draw_scaled_pixmap(painter, self._overlay_top_pixmap, base_rect)

        painter.end()

        self.setText("")
        self.setPixmap(canvas)


class ThumbnailList(QListWidget):
    set_left_requested = Signal(int)
    set_right_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWrapping(False)
        self.setSpacing(8)
        self.setIconSize(QSize(140, 80))
        self.setMinimumHeight(140)

        self.setStyleSheet("""
            QListWidget {
                background: #202020;
                color: #dddddd;
                border: 1px solid #444444;
            }
            QListWidget::item {
                padding: 4px;
                border: 1px solid transparent;
            }
            QListWidget::item:selected {
                border: 2px solid #4da3ff;
                background: #2b2b2b;
            }
        """)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item is None:
            return

        index = self.row(item)

        menu = QMenu(self)
        act_right = QAction("右のメイン表示にする", self)
        act_left = QAction("左の補助表示にする", self)

        act_right.triggered.connect(lambda: self.set_right_requested.emit(index))
        act_left.triggered.connect(lambda: self.set_left_requested.emit(index))

        menu.addAction(act_right)
        menu.addAction(act_left)
        menu.exec(event.globalPos())


class MainWindow(QMainWindow):
    VIEW_MODE_DEFAULT = "default"
    VIEW_MODE_VERTICAL = "vertical"
    VIEW_MODE_FOCUS = "focus"
    VIEW_MODE_RIGHT_EXPANDED = "right_expanded"
    VIEW_MODE_IMAGE_ONLY = "image_only"
    VIEW_MODE_IMAGE_ONLY_BOTH = "image_only_both"

    SETTINGS_FILE_NAME = "settings.json"
    AUTO_PLAY_INTERVAL_MS = 2000
    ZOOM_STEP = 1.25
    ZOOM_MIN = 0.25
    ZOOM_MAX = 8.0

    def __init__(self):
        super().__init__()

        self.setWindowTitle("画像ビューアー")
        self.resize(1400, 900)

        self.image_paths: list[Path] = []
        self.current_index = 0
        self.left_index = 0
        self.left_manual_path: Path | None = None

        self.right_underlay_path: Path | None = None
        self.right_overlay_bottom_path: Path | None = None
        self.right_overlay_middle_path: Path | None = None
        self.right_overlay_top_path: Path | None = None

        self.current_view_mode = self.VIEW_MODE_DEFAULT
        self.right_zoom_factor = 1.0

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.next_page)

        self.settings_path = Path(__file__).resolve().parent / self.SETTINGS_FILE_NAME
        self.settings_data = self.load_settings()

        self._build_ui()
        self.apply_view_mode(self.VIEW_MODE_DEFAULT)

    def default_settings(self):
        return {
            "last_main_dir": "",
            "last_left_image_dir": "",
            "last_underlay_dir": "",
            "last_overlay_dir": "",
        }

    def load_settings(self):
        defaults = self.default_settings()

        if not self.settings_path.exists():
            return defaults

        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            if not isinstance(loaded, dict):
                return defaults

            settings = defaults.copy()
            settings.update({
                "last_main_dir": str(loaded.get("last_main_dir", "")),
                "last_left_image_dir": str(loaded.get("last_left_image_dir", "")),
                "last_underlay_dir": str(loaded.get("last_underlay_dir", "")),
                "last_overlay_dir": str(loaded.get("last_overlay_dir", "")),
            })
            return settings
        except Exception:
            return defaults

    def save_settings(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(
                self,
                "設定保存エラー",
                f"settings.json の保存に失敗しました。\n{e}"
            )

    def get_existing_dir_or_fallback(self, key: str) -> str:
        raw = self.settings_data.get(key, "")
        if not raw:
            return ""

        p = Path(raw)
        if p.exists() and p.is_dir():
            return str(p)
        return ""

    def _build_ui(self):
        self.toolbar = QToolBar("Toolbar")
        self.addToolBar(self.toolbar)

        self.btn_open_folder = QPushButton("フォルダを開く")
        self.btn_prev = QPushButton("前へ")
        self.btn_next = QPushButton("次へ")
        self.btn_set_left = QPushButton("左画像を選ぶ")
        self.btn_reset_left = QPushButton("左画像を自動に戻す")

        self.btn_set_right_underlay = QPushButton("右背景を選ぶ")
        self.btn_reset_right_underlay = QPushButton("右背景解除")

        self.btn_set_right_overlay_bottom = QPushButton("右オーバーレイ下")
        self.btn_reset_right_overlay_bottom = QPushButton("下解除")
        self.btn_set_right_overlay_middle = QPushButton("右オーバーレイ中")
        self.btn_reset_right_overlay_middle = QPushButton("中解除")
        self.btn_set_right_overlay_top = QPushButton("右オーバーレイ上")
        self.btn_reset_right_overlay_top = QPushButton("上解除")

        self.btn_mode_default = QPushButton("通常モード")
        self.btn_mode_vertical = QPushButton("縦スライドモード")
        self.btn_mode_focus = QPushButton("集中モード")
        self.btn_mode_right_expanded = QPushButton("右拡大モード")
        self.btn_mode_image_only = QPushButton("画像だけモード")
        self.btn_mode_image_only_both = QPushButton("両画像だけモード")

        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_next.clicked.connect(self.next_page)
        self.btn_set_left.clicked.connect(self.choose_left_image)
        self.btn_reset_left.clicked.connect(self.reset_left_image)

        self.btn_set_right_underlay.clicked.connect(self.choose_right_underlay)
        self.btn_reset_right_underlay.clicked.connect(self.reset_right_underlay)

        self.btn_set_right_overlay_bottom.clicked.connect(self.choose_right_overlay_bottom)
        self.btn_reset_right_overlay_bottom.clicked.connect(self.reset_right_overlay_bottom)
        self.btn_set_right_overlay_middle.clicked.connect(self.choose_right_overlay_middle)
        self.btn_reset_right_overlay_middle.clicked.connect(self.reset_right_overlay_middle)
        self.btn_set_right_overlay_top.clicked.connect(self.choose_right_overlay_top)
        self.btn_reset_right_overlay_top.clicked.connect(self.reset_right_overlay_top)

        self.btn_mode_default.clicked.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_DEFAULT)
        )
        self.btn_mode_vertical.clicked.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_VERTICAL)
        )
        self.btn_mode_focus.clicked.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_FOCUS)
        )
        self.btn_mode_right_expanded.clicked.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_RIGHT_EXPANDED)
        )
        self.btn_mode_image_only.clicked.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_IMAGE_ONLY)
        )
        self.btn_mode_image_only_both.clicked.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_IMAGE_ONLY_BOTH)
        )

        self.toolbar.addWidget(self.btn_open_folder)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.btn_prev)
        self.toolbar.addWidget(self.btn_next)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.btn_set_left)
        self.toolbar.addWidget(self.btn_reset_left)
        self.toolbar.addSeparator()

        self.toolbar.addWidget(self.btn_set_right_underlay)
        self.toolbar.addWidget(self.btn_reset_right_underlay)
        self.toolbar.addSeparator()

        self.toolbar.addWidget(self.btn_set_right_overlay_bottom)
        self.toolbar.addWidget(self.btn_reset_right_overlay_bottom)
        self.toolbar.addWidget(self.btn_set_right_overlay_middle)
        self.toolbar.addWidget(self.btn_reset_right_overlay_middle)
        self.toolbar.addWidget(self.btn_set_right_overlay_top)
        self.toolbar.addWidget(self.btn_reset_right_overlay_top)
        self.toolbar.addSeparator()

        self.toolbar.addWidget(self.btn_mode_default)
        self.toolbar.addWidget(self.btn_mode_vertical)
        self.toolbar.addWidget(self.btn_mode_focus)
        self.toolbar.addWidget(self.btn_mode_right_expanded)
        self.toolbar.addWidget(self.btn_mode_image_only)
        self.toolbar.addWidget(self.btn_mode_image_only_both)

        self.folder_label = QLabel("フォルダ未選択")
        self.page_label = QLabel("0 / 0")
        self.left_mode_label = QLabel("左画像: 自動")
        self.right_underlay_label = QLabel("右背景: なし")
        self.right_overlay_bottom_label = QLabel("下: なし")
        self.right_overlay_middle_label = QLabel("中: なし")
        self.right_overlay_top_label = QLabel("上: なし")
        self.view_mode_label = QLabel("表示モード: 通常")
        self.zoom_label = QLabel("ズーム: 100%")
        self.auto_play_label = QLabel("自動再生: 停止")

        for label in (
            self.folder_label,
            self.page_label,
            self.left_mode_label,
            self.right_underlay_label,
            self.right_overlay_bottom_label,
            self.right_overlay_middle_label,
            self.right_overlay_top_label,
            self.view_mode_label,
            self.zoom_label,
            self.auto_play_label,
        ):
            label.setStyleSheet("color: #dddddd; padding: 4px;")

        self.info_widget = QWidget()
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.addWidget(self.folder_label, 1)
        info_layout.addWidget(self.left_mode_label, 0)
        info_layout.addWidget(self.right_underlay_label, 0)
        info_layout.addWidget(self.right_overlay_bottom_label, 0)
        info_layout.addWidget(self.right_overlay_middle_label, 0)
        info_layout.addWidget(self.right_overlay_top_label, 0)
        info_layout.addWidget(self.view_mode_label, 0)
        info_layout.addWidget(self.zoom_label, 0)
        info_layout.addWidget(self.auto_play_label, 0)
        info_layout.addWidget(self.page_label, 0)

        self.left_view = AspectImageLabel("左の補助表示", target_ratio=9 / 16)
        self.right_view = AspectImageLabel("右のメイン表示", target_ratio=16 / 9)

        self.left_view.context_menu_requested.connect(
            self.show_left_view_context_menu
        )

        self.right_view.wheel_up.connect(self.prev_page)
        self.right_view.wheel_down.connect(self.next_page)
        self.right_view.ctrl_wheel_up.connect(self.zoom_in)
        self.right_view.ctrl_wheel_down.connect(self.zoom_out)
        self.right_view.context_menu_requested.connect(
            self.show_right_view_context_menu
        )

        self.left_panel = self._make_panel("左の補助表示", self.left_view)
        self.right_panel = self._make_panel("右のメイン表示", self.right_view)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([420, 980])

        self.thumbnail_list = ThumbnailList()
        self.thumbnail_list.itemClicked.connect(self.on_thumbnail_clicked)
        self.thumbnail_list.set_left_requested.connect(self.set_left_by_index)
        self.thumbnail_list.set_right_requested.connect(self.set_current_index)

        self.thumb_panel = self._make_panel("ページ一覧", self.thumbnail_list)

        central = QWidget()
        self.setCentralWidget(central)

        self.root_layout = QVBoxLayout(central)
        self.root_layout.setContentsMargins(8, 8, 8, 8)
        self.root_layout.setSpacing(8)
        self.root_layout.addWidget(self.info_widget)
        self.root_layout.addWidget(self.splitter, 1)
        self.root_layout.addWidget(self.thumb_panel, 0)

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #2b2b2b;
                color: #eaeaea;
                font-size: 14px;
            }
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #555555;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background: #4a4a4a;
            }
        """)

    def _make_panel(self, title: str, content: QWidget) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("""
            QFrame {
                background: #252525;
                border: 1px solid #444444;
            }
        """)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-weight: bold;
                padding: 4px 2px;
            }
        """)

        layout.addWidget(title_label)
        layout.addWidget(content, 1)
        return frame

    def update_zoom_label(self):
        self.zoom_label.setText(f"ズーム: {int(self.right_zoom_factor * 100)}%")

    def update_auto_play_label(self):
        state = "再生中" if self.auto_timer.isActive() else "停止"
        self.auto_play_label.setText(f"自動再生: {state}")

    def _label_text_from_path(self, prefix: str, path: Path | None):
        if path is not None and path.exists():
            return f"{prefix}: {path.name}"
        return f"{prefix}: なし"

    def update_right_layer_labels(self):
        self.right_underlay_label.setText(
            self._label_text_from_path("右背景", self.right_underlay_path)
        )
        self.right_overlay_bottom_label.setText(
            self._label_text_from_path("下", self.right_overlay_bottom_path)
        )
        self.right_overlay_middle_label.setText(
            self._label_text_from_path("中", self.right_overlay_middle_path)
        )
        self.right_overlay_top_label.setText(
            self._label_text_from_path("上", self.right_overlay_top_path)
        )

    def apply_right_zoom(self):
        self.right_view.set_zoom_factor(self.right_zoom_factor)
        self.update_zoom_label()

    def zoom_in(self):
        self.right_zoom_factor = min(self.ZOOM_MAX, self.right_zoom_factor * self.ZOOM_STEP)
        self.apply_right_zoom()

    def zoom_out(self):
        self.right_zoom_factor = max(self.ZOOM_MIN, self.right_zoom_factor / self.ZOOM_STEP)
        self.apply_right_zoom()

    def reset_zoom(self):
        self.right_zoom_factor = 1.0
        self.apply_right_zoom()

    def start_auto_play(self):
        self.auto_timer.start(self.AUTO_PLAY_INTERVAL_MS)
        self.update_auto_play_label()

    def stop_auto_play(self):
        self.auto_timer.stop()
        self.update_auto_play_label()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.right_view.setFocus()

    def apply_view_mode(self, mode: str):
        self.current_view_mode = mode

        self.toolbar.setVisible(True)
        self.info_widget.setVisible(True)
        self.left_panel.setVisible(True)
        self.thumb_panel.setVisible(True)

        if mode == self.VIEW_MODE_DEFAULT:
            self.right_view.set_target_ratio(16 / 9)
            self.splitter.setSizes([420, 980])
            self.view_mode_label.setText("表示モード: 通常")

        elif mode == self.VIEW_MODE_VERTICAL:
            self.right_view.set_target_ratio(9 / 16)
            self.splitter.setSizes([420, 980])
            self.view_mode_label.setText("表示モード: 縦スライド")

        elif mode == self.VIEW_MODE_FOCUS:
            self.right_view.set_target_ratio(16 / 9)
            self.thumb_panel.setVisible(False)
            self.splitter.setSizes([420, 980])
            self.view_mode_label.setText("表示モード: 集中")

        elif mode == self.VIEW_MODE_RIGHT_EXPANDED:
            self.right_view.set_target_ratio(16 / 9)
            self.thumb_panel.setVisible(False)
            self.splitter.setSizes([180, 1220])
            self.view_mode_label.setText("表示モード: 右拡大")

        elif mode == self.VIEW_MODE_IMAGE_ONLY:
            self.right_view.set_target_ratio(None)
            self.toolbar.setVisible(False)
            self.info_widget.setVisible(False)
            self.left_panel.setVisible(False)
            self.thumb_panel.setVisible(False)
            self.view_mode_label.setText("表示モード: 画像だけ")

        elif mode == self.VIEW_MODE_IMAGE_ONLY_BOTH:
            self.right_view.set_target_ratio(16 / 9)
            self.toolbar.setVisible(False)
            self.info_widget.setVisible(False)
            self.left_panel.setVisible(True)
            self.thumb_panel.setVisible(False)
            self.splitter.setSizes([420, 980])
            self.view_mode_label.setText("表示モード: 両画像だけ")

        self.refresh_views()
        self.right_view.setFocus()

    def show_left_view_context_menu(self, global_pos):
        menu = QMenu(self)

        act_choose_left = QAction("左画像を選ぶ", self)
        act_reset_left = QAction("左画像を自動に戻す", self)

        act_choose_left.triggered.connect(self.choose_left_image)
        act_reset_left.triggered.connect(self.reset_left_image)

        menu.addAction(act_choose_left)
        menu.addAction(act_reset_left)
        menu.exec(global_pos)

    def show_right_view_context_menu(self, global_pos):
        menu = QMenu(self)

        act_open_folder = QAction("フォルダを開く", self)

        act_choose_underlay = QAction("右背景を選ぶ", self)
        act_reset_underlay = QAction("右背景解除", self)

        act_choose_bottom = QAction("右オーバーレイ下を選ぶ", self)
        act_reset_bottom = QAction("右オーバーレイ下を解除", self)
        act_choose_middle = QAction("右オーバーレイ中を選ぶ", self)
        act_reset_middle = QAction("右オーバーレイ中を解除", self)
        act_choose_top = QAction("右オーバーレイ上を選ぶ", self)
        act_reset_top = QAction("右オーバーレイ上を解除", self)

        act_default = QAction("通常モード", self)
        act_vertical = QAction("縦スライドモード", self)
        act_focus = QAction("集中モード", self)
        act_right_expanded = QAction("右拡大モード", self)
        act_image_only = QAction("画像だけモード", self)
        act_image_only_both = QAction("両画像だけモード", self)

        act_zoom_in = QAction("ズームイン", self)
        act_zoom_out = QAction("ズームアウト", self)
        act_zoom_reset = QAction("ズームリセット", self)

        act_auto_start = QAction("自動再生開始", self)
        act_auto_stop = QAction("自動再生停止", self)

        act_fullscreen = QAction("フルスクリーン切替", self)

        act_prev = QAction("前へ", self)
        act_next = QAction("次へ", self)

        act_open_folder.triggered.connect(self.open_folder)

        act_choose_underlay.triggered.connect(self.choose_right_underlay)
        act_reset_underlay.triggered.connect(self.reset_right_underlay)

        act_choose_bottom.triggered.connect(self.choose_right_overlay_bottom)
        act_reset_bottom.triggered.connect(self.reset_right_overlay_bottom)
        act_choose_middle.triggered.connect(self.choose_right_overlay_middle)
        act_reset_middle.triggered.connect(self.reset_right_overlay_middle)
        act_choose_top.triggered.connect(self.choose_right_overlay_top)
        act_reset_top.triggered.connect(self.reset_right_overlay_top)

        act_default.triggered.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_DEFAULT)
        )
        act_vertical.triggered.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_VERTICAL)
        )
        act_focus.triggered.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_FOCUS)
        )
        act_right_expanded.triggered.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_RIGHT_EXPANDED)
        )
        act_image_only.triggered.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_IMAGE_ONLY)
        )
        act_image_only_both.triggered.connect(
            lambda: self.apply_view_mode(self.VIEW_MODE_IMAGE_ONLY_BOTH)
        )

        act_zoom_in.triggered.connect(self.zoom_in)
        act_zoom_out.triggered.connect(self.zoom_out)
        act_zoom_reset.triggered.connect(self.reset_zoom)

        act_auto_start.triggered.connect(self.start_auto_play)
        act_auto_stop.triggered.connect(self.stop_auto_play)

        act_fullscreen.triggered.connect(self.toggle_fullscreen)

        act_prev.triggered.connect(self.prev_page)
        act_next.triggered.connect(self.next_page)

        menu.addAction(act_open_folder)
        menu.addSeparator()

        menu.addAction(act_choose_underlay)
        menu.addAction(act_reset_underlay)
        menu.addSeparator()

        menu.addAction(act_choose_bottom)
        menu.addAction(act_reset_bottom)
        menu.addAction(act_choose_middle)
        menu.addAction(act_reset_middle)
        menu.addAction(act_choose_top)
        menu.addAction(act_reset_top)
        menu.addSeparator()

        menu.addAction(act_default)
        menu.addAction(act_vertical)
        menu.addAction(act_focus)
        menu.addAction(act_right_expanded)
        menu.addSeparator()
        menu.addAction(act_image_only)
        menu.addAction(act_image_only_both)
        menu.addSeparator()

        menu.addAction(act_zoom_in)
        menu.addAction(act_zoom_out)
        menu.addAction(act_zoom_reset)
        menu.addSeparator()

        menu.addAction(act_auto_start)
        menu.addAction(act_auto_stop)
        menu.addSeparator()

        menu.addAction(act_fullscreen)
        menu.addSeparator()

        menu.addAction(act_prev)
        menu.addAction(act_next)

        menu.exec(global_pos)

    def open_folder(self):
        initial_dir = self.get_existing_dir_or_fallback("last_main_dir")

        folder = QFileDialog.getExistingDirectory(
            self,
            "画像フォルダを選択",
            initial_dir
        )
        if not folder:
            return

        folder_path = Path(folder)
        self.settings_data["last_main_dir"] = str(folder_path)
        self.save_settings()
        self.load_images_from_folder(folder_path)

    def load_images_from_folder(self, folder_path: Path):
        if not folder_path.exists() or not folder_path.is_dir():
            QMessageBox.warning(self, "エラー", "有効なフォルダではありません。")
            return

        images = []
        for p in folder_path.iterdir():
            if p.is_file() and p.suffix.casefold() in IMAGE_EXTS:
                images.append(p)

        images.sort(key=natural_key)

        self.image_paths = images
        self.current_index = 0
        self.left_index = 0
        self.left_manual_path = None
        self.folder_label.setText(str(folder_path))

        self.refresh_thumbnails()
        self.refresh_views()

        if not self.image_paths:
            QMessageBox.information(
                self,
                "画像なし",
                "このフォルダには対応画像が見つかりませんでした。"
            )

    def refresh_thumbnails(self):
        self.thumbnail_list.clear()

        for i, path in enumerate(self.image_paths):
            item = QListWidgetItem(f"{i + 1}\n{path.name}")

            pix = QPixmap(str(path))
            if not pix.isNull():
                thumb = pix.scaled(
                    140,
                    80,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                item.setIcon(QIcon(thumb))

            self.thumbnail_list.addItem(item)

        if self.image_paths:
            self.thumbnail_list.setCurrentRow(self.current_index)

    def refresh_views(self):
        if not self.image_paths:
            self.left_view.set_image(None)
            self.right_view.set_image(None)
            self.page_label.setText("0 / 0")
            self.left_mode_label.setText("左画像: なし")
            self.update_right_layer_labels()
            self.update_zoom_label()
            self.update_auto_play_label()
            return

        if self.left_manual_path is not None and self.left_manual_path.exists():
            left_path = str(self.left_manual_path)
            self.left_mode_label.setText(f"左画像: 手動 ({self.left_manual_path.name})")
        else:
            left_path = str(self.image_paths[self.left_index])
            self.left_mode_label.setText(f"左画像: 自動 ({self.image_paths[self.left_index].name})")

        right_path = str(self.image_paths[self.current_index])

        self.left_view.set_image(left_path)
        self.right_view.set_image(right_path)

        self.right_view.set_underlay(
            str(self.right_underlay_path) if self.right_underlay_path and self.right_underlay_path.exists() else None
        )
        self.right_view.set_overlay_bottom(
            str(self.right_overlay_bottom_path) if self.right_overlay_bottom_path and self.right_overlay_bottom_path.exists() else None
        )
        self.right_view.set_overlay_middle(
            str(self.right_overlay_middle_path) if self.right_overlay_middle_path and self.right_overlay_middle_path.exists() else None
        )
        self.right_view.set_overlay_top(
            str(self.right_overlay_top_path) if self.right_overlay_top_path and self.right_overlay_top_path.exists() else None
        )

        self.apply_right_zoom()

        self.page_label.setText(f"{self.current_index + 1} / {len(self.image_paths)}")
        self.thumbnail_list.setCurrentRow(self.current_index)
        self.update_right_layer_labels()
        self.update_auto_play_label()

    def on_thumbnail_clicked(self, item: QListWidgetItem):
        index = self.thumbnail_list.row(item)
        self.set_current_index(index)

    def set_current_index(self, index: int):
        if not self.image_paths:
            return
        if 0 <= index < len(self.image_paths):
            self.current_index = index
            self.refresh_views()

    def set_left_by_index(self, index: int):
        if not self.image_paths:
            return
        if 0 <= index < len(self.image_paths):
            self.left_manual_path = None
            self.left_index = index
            self.refresh_views()

    def prev_page(self):
        if not self.image_paths:
            return
        self.current_index = max(0, self.current_index - 1)
        self.refresh_views()

    def next_page(self):
        if not self.image_paths:
            return
        self.current_index = min(len(self.image_paths) - 1, self.current_index + 1)
        self.refresh_views()

    def choose_left_image(self):
        initial_dir = self.get_existing_dir_or_fallback("last_left_image_dir")

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "左に表示する画像を選択",
            initial_dir,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if not file_path:
            return

        chosen_path = Path(file_path)
        self.left_manual_path = chosen_path
        self.settings_data["last_left_image_dir"] = str(chosen_path.parent)
        self.save_settings()
        self.refresh_views()

    def reset_left_image(self):
        self.left_manual_path = None
        self.left_index = 0
        self.refresh_views()

    def choose_right_underlay(self):
        initial_dir = self.get_existing_dir_or_fallback("last_underlay_dir")

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "右背景画像を選択",
            initial_dir,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if not file_path:
            return

        chosen_path = Path(file_path)
        self.right_underlay_path = chosen_path
        self.settings_data["last_underlay_dir"] = str(chosen_path.parent)
        self.save_settings()
        self.refresh_views()

    def reset_right_underlay(self):
        self.right_underlay_path = None
        self.refresh_views()

    def _choose_overlay_common(self, dialog_title: str):
        initial_dir = self.get_existing_dir_or_fallback("last_overlay_dir")

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            dialog_title,
            initial_dir,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
        )
        if not file_path:
            return None

        chosen_path = Path(file_path)
        self.settings_data["last_overlay_dir"] = str(chosen_path.parent)
        self.save_settings()
        return chosen_path

    def choose_right_overlay_bottom(self):
        chosen_path = self._choose_overlay_common("右オーバーレイ下を選択")
        if chosen_path is None:
            return
        self.right_overlay_bottom_path = chosen_path
        self.refresh_views()

    def reset_right_overlay_bottom(self):
        self.right_overlay_bottom_path = None
        self.refresh_views()

    def choose_right_overlay_middle(self):
        chosen_path = self._choose_overlay_common("右オーバーレイ中を選択")
        if chosen_path is None:
            return
        self.right_overlay_middle_path = chosen_path
        self.refresh_views()

    def reset_right_overlay_middle(self):
        self.right_overlay_middle_path = None
        self.refresh_views()

    def choose_right_overlay_top(self):
        chosen_path = self._choose_overlay_common("右オーバーレイ上を選択")
        if chosen_path is None:
            return
        self.right_overlay_top_path = chosen_path
        self.refresh_views()

    def reset_right_overlay_top(self):
        self.right_overlay_top_path = None
        self.refresh_views()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.prev_page()
            return

        if event.key() == Qt.Key_Right:
            self.next_page()
            return

        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            return

        if event.key() == Qt.Key_0 and QApplication.keyboardModifiers() & Qt.ControlModifier:
            self.reset_zoom()
            return

        if event.key() == Qt.Key_Escape:
            self.stop_auto_play()

            if self.isFullScreen():
                self.showNormal()
                self.right_view.setFocus()
                return

            if self.current_view_mode in (
                self.VIEW_MODE_IMAGE_ONLY,
                self.VIEW_MODE_IMAGE_ONLY_BOTH,
            ):
                self.apply_view_mode(self.VIEW_MODE_DEFAULT)
                return

        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
