import json
import re
import sys
import unicodedata
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal, QRect
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
    context_menu_requested = Signal(object)

    def __init__(self, empty_text="", target_ratio=None, parent=None):
        super().__init__(parent)
        self.empty_text = empty_text
        self.target_ratio = target_ratio

        self._base_pixmap = None
        self._overlay_pixmap = None

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

    def set_overlay(self, overlay_path: str | None):
        if not overlay_path:
            self._overlay_pixmap = None
            self._update_scaled_pixmap()
            return

        pixmap = QPixmap(overlay_path)
        if pixmap.isNull():
            self._overlay_pixmap = None
            self._update_scaled_pixmap()
            return

        self._overlay_pixmap = pixmap
        self._update_scaled_pixmap()

    def set_target_ratio(self, ratio: float | None):
        self.target_ratio = ratio
        self._update_scaled_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
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

        img_ratio = src_w / src_h
        box_ratio = box_w / box_h

        if img_ratio > box_ratio:
            draw_w = box_w
            draw_h = int(draw_w / img_ratio)
        else:
            draw_h = box_h
            draw_w = int(draw_h * img_ratio)

        offset_x = (box_w - draw_w) // 2
        offset_y = (box_h - draw_h) // 2

        canvas_x = (area_w - box_w) // 2
        canvas_y = (area_h - box_h) // 2

        return QRect(canvas_x + offset_x, canvas_y + offset_y, draw_w, draw_h)

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
        painter.drawPixmap(base_rect, self._base_pixmap)

        if self._overlay_pixmap is not None:
            overlay_scaled = self._overlay_pixmap.scaled(
                base_rect.size(),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            )
            painter.drawPixmap(base_rect.topLeft(), overlay_scaled)

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

    def __init__(self):
        super().__init__()

        self.setWindowTitle("画像ビューアー")
        self.resize(1400, 900)

        self.image_paths: list[Path] = []
        self.current_index = 0
        self.left_index = 0
        self.left_manual_path: Path | None = None
        self.right_overlay_path: Path | None = None
        self.current_view_mode = self.VIEW_MODE_DEFAULT

        self.settings_path = Path(__file__).resolve().parent / self.SETTINGS_FILE_NAME
        self.settings_data = self.load_settings()

        self._build_ui()
        self.apply_view_mode(self.VIEW_MODE_DEFAULT)

    def default_settings(self):
        return {
            "last_main_dir": "",
            "last_left_image_dir": "",
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
        self.btn_set_right_overlay = QPushButton("右オーバーレイを選ぶ")
        self.btn_reset_right_overlay = QPushButton("右オーバーレイ解除")

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
        self.btn_set_right_overlay.clicked.connect(self.choose_right_overlay)
        self.btn_reset_right_overlay.clicked.connect(self.reset_right_overlay)

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
        self.toolbar.addWidget(self.btn_set_right_overlay)
        self.toolbar.addWidget(self.btn_reset_right_overlay)
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
        self.right_overlay_label = QLabel("右オーバーレイ: なし")
        self.view_mode_label = QLabel("表示モード: 通常")

        self.folder_label.setStyleSheet("color: #dddddd; padding: 4px;")
        self.page_label.setStyleSheet("color: #dddddd; padding: 4px;")
        self.left_mode_label.setStyleSheet("color: #dddddd; padding: 4px;")
        self.right_overlay_label.setStyleSheet("color: #dddddd; padding: 4px;")
        self.view_mode_label.setStyleSheet("color: #dddddd; padding: 4px;")

        self.info_widget = QWidget()
        info_layout = QHBoxLayout(self.info_widget)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.addWidget(self.folder_label, 1)
        info_layout.addWidget(self.left_mode_label, 0)
        info_layout.addWidget(self.right_overlay_label, 0)
        info_layout.addWidget(self.view_mode_label, 0)
        info_layout.addWidget(self.page_label, 0)

        self.left_view = AspectImageLabel("左の補助表示", target_ratio=9 / 16)
        self.right_view = AspectImageLabel("右のメイン表示", target_ratio=16 / 9)

        self.right_view.wheel_up.connect(self.prev_page)
        self.right_view.wheel_down.connect(self.next_page)
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
                padding: 6px 12px;
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

    def show_right_view_context_menu(self, global_pos):
        menu = QMenu(self)

        act_default = QAction("通常モード", self)
        act_vertical = QAction("縦スライドモード", self)
        act_focus = QAction("集中モード", self)
        act_right_expanded = QAction("右拡大モード", self)
        act_image_only = QAction("画像だけモード", self)
        act_image_only_both = QAction("両画像だけモード", self)

        act_prev = QAction("前へ", self)
        act_next = QAction("次へ", self)

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

        act_prev.triggered.connect(self.prev_page)
        act_next.triggered.connect(self.next_page)

        menu.addAction(act_default)
        menu.addAction(act_vertical)
        menu.addAction(act_focus)
        menu.addAction(act_right_expanded)
        menu.addSeparator()
        menu.addAction(act_image_only)
        menu.addAction(act_image_only_both)
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
            self.right_overlay_label.setText("右オーバーレイ: なし")
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

        if self.right_overlay_path is not None and self.right_overlay_path.exists():
            self.right_view.set_overlay(str(self.right_overlay_path))
            self.right_overlay_label.setText(f"右オーバーレイ: {self.right_overlay_path.name}")
        else:
            self.right_view.set_overlay(None)
            self.right_overlay_label.setText("右オーバーレイ: なし")

        self.page_label.setText(f"{self.current_index + 1} / {len(self.image_paths)}")
        self.thumbnail_list.setCurrentRow(self.current_index)

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

    def choose_right_overlay(self):
        initial_dir = self.get_existing_dir_or_fallback("last_overlay_dir")

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "右に重ねるオーバーレイ画像を選択",
            initial_dir,
            "Images (*.png *.webp *.jpg *.jpeg *.bmp *.gif)"
        )
        if not file_path:
            return

        chosen_path = Path(file_path)
        self.right_overlay_path = chosen_path
        self.settings_data["last_overlay_dir"] = str(chosen_path.parent)
        self.save_settings()
        self.refresh_views()

    def reset_right_overlay(self):
        self.right_overlay_path = None
        self.refresh_views()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.prev_page()
            return

        if event.key() == Qt.Key_Right:
            self.next_page()
            return

        if event.key() == Qt.Key_Escape and self.current_view_mode in (
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
