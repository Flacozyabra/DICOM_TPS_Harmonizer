from datetime import datetime
import json
import os
import sys
import platform
import threading
import urllib.request
import re
import math
from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize, QPoint, QByteArray, QThread, QPointF, QRect, QEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QLineEdit, QCheckBox, QProgressBar,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QFileDialog, QDialog,
    QGridLayout, QMessageBox, QApplication, QSplitter, QSizePolicy,
    QSlider, QStackedWidget, QComboBox
)
from PyQt6.QtGui import QIcon, QFont, QTextCursor, QPixmap, QBrush, QColor, QPainter, QPen, QImage, QLinearGradient, QPolygon, QDragEnterEvent, QDropEvent, QDragMoveEvent

from src.core.config import ProcessingConfig
from src.core.processor import DicomProcessor
from src.utils.logger import BaseLogger
from src.gui.threads import UpdateCheckerThread
from src.gui.dialogs import CustomQuestionDialog, UpdateDialog, PatientEditDialog, ScanProgressDialog
from src.gui.widgets import LanguageSwitch, HUVerticalSlider, DicomViewerWidget, DicomViewerPanel, CustomSplitter
from src.gui.styles import set_dark_titlebar





# Сигнальный мост для безопасной передачи сообщений из фоновых потоков в GUI
class QtSignalBridge(QObject):
    log_signal = pyqtSignal(str, str)          # text, tag
    progress_signal = pyqtSignal(int, int)      # current, total
    scan_progress_signal = pyqtSignal(int, int) # current, total
    finished_signal = pyqtSignal()
    tree_scanned_signal = pyqtSignal(dict)


# Адаптер логгера для отправки сообщений через сигналы Qt
class QtLogger(BaseLogger):
    def __init__(self, bridge: QtSignalBridge) -> None:
        self.bridge = bridge

    def log(self, text: str, tag: str = "info") -> None:
        self.bridge.log_signal.emit(text, tag)

    def update_progress(self, current: int, total: int) -> None:
        self.bridge.progress_signal.emit(current, total)

    def update_scan_progress(self, current: int, total: int) -> None:
        self.bridge.scan_progress_signal.emit(current, total)


class DicomSplitterApp(QMainWindow):
    """Главный класс графического интерфейса приложения DICOM TPS Harmonizer на PyQt6."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("DICOM TPS Harmonizer")

        # Определение путей к ресурсам относительно корня проекта с поддержкой PyInstaller
        if getattr(sys, "frozen", False):
            self.project_root = Path(sys._MEIPASS)
        else:
            self.project_root = Path(__file__).resolve().parents[2]
        
        icon_path = self.project_root / "themes" / "app_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setMinimumSize(1000, 640)
        self.resize(1100, 720)
        self.setAcceptDrops(True)

        # Инициализация моста сигналов
        self.bridge = QtSignalBridge()
        self.bridge.log_signal.connect(self.add_log)
        self.bridge.progress_signal.connect(self.update_progress)
        self.bridge.scan_progress_signal.connect(self.update_scan_progress)
        self.bridge.tree_scanned_signal.connect(self.on_tree_scanned)
        self.bridge.finished_signal.connect(self.on_processing_finished)

        self.THEMES = {
            "dark": {
                "MAIN_BG": "#121212",
                "PANEL_BG": "#1A1A1A",
                "TEXT_COLOR": "#D1D5DB",
                "TEXT_LIGHT": "#FFFFFF",
                "TEXT_MUTED": "#A0A0A0",
                "BORDER_COLOR": "#2D2D2D",
                "BORDER_COLOR_ALT": "#374151",
                "BUTTON_BG": "#2A2A2A",
                "BUTTON_HOVER_BG": "#374151",
                "BUTTON_PRESSED_BG": "#1F2937",
                "ACCENT_COLOR": "#3B82F6",
                "ACCENT_COLOR_DARK": "#2563EB",
                "ACCENT_COLOR_DEEP": "#1D4ED8",
                "PROGRESS_BG": "#151515",
                "PROGRESS_BORDER": "#333333",
                "GRADIENT_START": "#3B82F6",
                "GRADIENT_END": "#8B5CF6",
                "ARROW_RIGHT_PATH": "arrow_right.png",
                "SPLITTER_COLOR": "#2D2D2D"
            },
            "light": {
                "MAIN_BG": "#E2E2E2",
                "PANEL_BG": "#F0F0F0",
                "TEXT_COLOR": "#202020",
                "TEXT_LIGHT": "#000000",
                "TEXT_MUTED": "#5E5E5E",
                "BORDER_COLOR": "#CCCCCC",
                "BORDER_COLOR_ALT": "#9E9E9E",
                "BUTTON_BG": "#D5D5D5",
                "BUTTON_HOVER_BG": "#C0C0C0",
                "BUTTON_PRESSED_BG": "#A0A0A0",
                "ACCENT_COLOR": "#757575",
                "ACCENT_COLOR_DARK": "#424242",
                "ACCENT_COLOR_DEEP": "#212121",
                "PROGRESS_BG": "#CCCCCC",
                "PROGRESS_BORDER": "#9E9E9E",
                "GRADIENT_START": "#757575",
                "GRADIENT_END": "#212121",
                "ARROW_RIGHT_PATH": "arrow_right_dark.png",
                "SPLITTER_COLOR": "#CCCCCC"
            },
            "red": {
                "MAIN_BG": "#1C0D11",
                "PANEL_BG": "#2D151B",
                "TEXT_COLOR": "#F9ECED",
                "TEXT_LIGHT": "#FFFFFF",
                "TEXT_MUTED": "#D4A3A9",
                "BORDER_COLOR": "#4E232E",
                "BORDER_COLOR_ALT": "#8A3B4E",
                "BUTTON_BG": "#5E2633",
                "BUTTON_HOVER_BG": "#7B3143",
                "BUTTON_PRESSED_BG": "#3F1922",
                "ACCENT_COLOR": "#E11D48",
                "ACCENT_COLOR_DARK": "#BE123C",
                "ACCENT_COLOR_DEEP": "#9F1239",
                "PROGRESS_BG": "#2D151B",
                "PROGRESS_BORDER": "#4E232E",
                "GRADIENT_START": "#E11D48",
                "GRADIENT_END": "#FDA4AF",
                "ARROW_RIGHT_PATH": "arrow_right.png",
                "SPLITTER_COLOR": "#4E232E"
            },
            "sunset": {
                "MAIN_BG": "#101E2E",
                "PANEL_BG": "#242F49",
                "TEXT_COLOR": "#D1D5DB",
                "TEXT_LIGHT": "#FFA586",
                "TEXT_MUTED": "#8A9BB4",
                "BORDER_COLOR": "#384358",
                "BORDER_COLOR_ALT": "#5871A2",
                "BUTTON_BG": "#3C4E70",
                "BUTTON_HOVER_BG": "#4D638E",
                "BUTTON_PRESSED_BG": "#2A374F",
                "ACCENT_COLOR": "#B51A2B",
                "ACCENT_COLOR_DARK": "#9A1624",
                "ACCENT_COLOR_DEEP": "#541A2E",
                "PROGRESS_BG": "#101E2E",
                "PROGRESS_BORDER": "#384358",
                "GRADIENT_START": "#FFA586",
                "GRADIENT_END": "#B51A2B",
                "ARROW_RIGHT_PATH": "arrow_right.png",
                "SPLITTER_COLOR": "#384358"
            },
            "cyber": {
                "MAIN_BG": "#0F0F0F",
                "PANEL_BG": "#202020",
                "TEXT_COLOR": "#D1D5DB",
                "TEXT_LIGHT": "#F8F8F8",
                "TEXT_MUTED": "#808080",
                "BORDER_COLOR": "#337418",
                "BORDER_COLOR_ALT": "#5DD62C",
                "BUTTON_BG": "#265912",
                "BUTTON_HOVER_BG": "#337418",
                "BUTTON_PRESSED_BG": "#0F0F0F",
                "ACCENT_COLOR": "#5DD62C",
                "ACCENT_COLOR_DARK": "#4CB323",
                "ACCENT_COLOR_DEEP": "#337418",
                "PROGRESS_BG": "#0F0F0F",
                "PROGRESS_BORDER": "#337418",
                "GRADIENT_START": "#5DD62C",
                "GRADIENT_END": "#337418",
                "ARROW_RIGHT_PATH": "arrow_right.png",
                "SPLITTER_COLOR": "#337418"
            }
        }

        # Загрузка путей и языка
        saved_input, saved_output, saved_lang, saved_theme = self.load_last_paths()
        self.current_lang = saved_lang
        self.current_theme = saved_theme
        
        
        self.translations: dict[str, str] = {}
        self.load_locale(self.current_lang)

        # Переводим плейсхолдеры
        if self.current_lang == "en":
            if saved_input == "Введите путь для папки Dicom_input":
                saved_input = self.loc("placeholder_input")
            if saved_output == "Введите путь для папки Dicom_output":
                saved_output = self.loc("placeholder_output")

        self.saved_input_path = saved_input
        self.saved_output_path = saved_output

        self.is_processing = False
        self.stop_event = threading.Event()
        self._is_updating_tree = False
        self.scan_dialog = None

        # Состояние вьюера
        self.viewer_active = False
        self.current_view_series_uid = None
        self.current_view_seg_idx = None

        # Создание интерфейса
        self.create_widgets()
        self.install_drag_drop_filters(self)
        self.apply_styles()
        self.update_locale_texts()
        self.center_on_screen()
        self.restore_window_state()

        self.VERSION = "2.0.0"
        self.check_updates()

    def check_updates(self) -> None:
        """Запускает фоновый поток для проверки обновлений с GitHub."""
        config_file = self.get_config_path()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("skip_update_check", False):
                        return
            except Exception:
                pass

        self.update_thread = UpdateCheckerThread(self.VERSION)
        self.update_thread.update_available.connect(self.on_update_available)
        self.update_thread.start()

    def on_update_available(self, new_version: str, release_url: str) -> None:
        """Показывает диалог предложения обновить программу при обнаружении новой версии."""
        config_file = self.get_config_path()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("skipped_version") == new_version:
                        return
            except Exception:
                pass

        dialog = UpdateDialog(self, new_version)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result_value
            if result == "yes":
                import webbrowser
                try:
                    webbrowser.open(release_url)
                except Exception:
                    pass
            elif result == "skip":
                self.save_skipped_version(new_version)

    def save_skipped_version(self, version: str) -> None:
        """Сохраняет версию, которую пользователь решил пропустить, в config.json."""
        config_file = self.get_config_path()
        config_data = {}
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass
        config_data["skipped_version"] = version
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def save_skip_update_check(self) -> None:
        """Сохраняет флаг отключения проверки обновлений в config.json."""
        config_file = self.get_config_path()
        config_data = {}
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass
        config_data["skip_update_check"] = True
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def get_config_path(self) -> Path:
        """Возвращает путь к файлу конфигурации в AppData пользователя."""
        appdata = os.getenv("APPDATA")
        if appdata:
            config_dir = Path(appdata) / "DicomTpsHarmonizer"
        else:
            config_dir = Path.home() / ".dicom_tps_harmonizer"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def generate_theme_arrows(self, color_right_hex: str, color_down_hex: str) -> tuple[str, str]:
        themes_dir = self.project_root / "themes"
        themes_dir.mkdir(exist_ok=True)
        path_right = themes_dir / "arrow_right_theme.png"
        path_down = themes_dir / "arrow_down_theme.png"
        try:
            from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
            from PyQt6.QtCore import Qt, QPointF
            
            # Стрелка вправо
            pixmap_right = QPixmap(16, 16)
            pixmap_right.fill(Qt.GlobalColor.transparent)
            painter_r = QPainter(pixmap_right)
            painter_r.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen_r = QPen(QColor(color_right_hex))
            pen_r.setWidthF(2.5)
            pen_r.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen_r.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter_r.setPen(pen_r)
            points_r = [QPointF(5.5, 3.5), QPointF(10.5, 8.0), QPointF(5.5, 12.5)]
            painter_r.drawPolyline(points_r)
            painter_r.end()
            pixmap_right.save(str(path_right), "PNG")
            
            # Стрелка вниз
            pixmap_down = QPixmap(16, 16)
            pixmap_down.fill(Qt.GlobalColor.transparent)
            painter_d = QPainter(pixmap_down)
            painter_d.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen_d = QPen(QColor(color_down_hex))
            pen_d.setWidthF(2.5)
            pen_d.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen_d.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter_d.setPen(pen_d)
            points_d = [QPointF(3.5, 5.5), QPointF(8.0, 10.5), QPointF(12.5, 5.5)]
            painter_d.drawPolyline(points_d)
            painter_d.end()
            pixmap_down.save(str(path_down), "PNG")
        except Exception:
            pass
        return path_right.as_posix(), path_down.as_posix()


    def on_theme_changed(self, index: int) -> None:
        theme_name = self.theme_combo.itemData(index)
        self.change_theme(theme_name)

    def change_theme(self, theme_name: str) -> None:
        if theme_name not in self.THEMES:
            theme_name = "dark"
        self.current_theme = theme_name
        self.apply_styles()
        self.save_last_paths()
        set_dark_titlebar(self)

    def load_last_paths(self) -> tuple[str, str, str, str]:
        config_file = self.get_config_path()
        inp = "Введите путь для папки Dicom_input"
        out = "Введите путь для папки Dicom_output"
        lang = "ru"
        theme = "dark"
        
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    inp_val = data.get("input_dir", "")
                    out_val = data.get("output_dir", "")
                    lang_val = data.get("language", "ru")
                    theme_val = data.get("theme", "dark")
                    if inp_val:
                        inp = inp_val
                    if out_val:
                        out = out_val
                    if lang_val:
                        lang = lang_val
                    if theme_val:
                        theme = theme_val
            except Exception:
                pass
        return inp, out, lang, theme

    def save_last_paths(self) -> None:
        inp = self.input_entry.text()
        out = self.output_entry.text()
        lang = self.current_lang
        theme = self.current_theme
        
        config_data = {}
        config_file = self.get_config_path()
        
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass
                
        if "Введите путь" not in inp and "Enter path" not in inp:
            config_data["input_dir"] = inp
        if "Введите путь" not in out and "Enter path" not in out:
            config_data["output_dir"] = out
            
        config_data["language"] = lang
        config_data["theme"] = theme
        
        # Сохраняем геометрию главного окна и состояние сплиттеров
        config_data["window_geometry"] = self.saveGeometry().toHex().data().decode('utf-8')
        if hasattr(self, "splitter"):
            config_data["splitter_state"] = self.splitter.saveState().toHex().data().decode('utf-8')
        if hasattr(self, "right_splitter"):
            config_data["right_splitter_state"] = self.right_splitter.saveState().toHex().data().decode('utf-8')
        
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def restore_window_state(self) -> None:
        config_file = self.get_config_path()
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                    # Восстановление геометрии главного окна
                    geom_hex = data.get("window_geometry", "")
                    if geom_hex:
                        self.restoreGeometry(QByteArray.fromHex(geom_hex.encode('utf-8')))
                        
                    # Восстановление состояния сплиттера
                    state_hex = data.get("splitter_state", "")
                    if state_hex and hasattr(self, "splitter"):
                        self.splitter.restoreState(QByteArray.fromHex(state_hex.encode('utf-8')))

                    # Восстановление состояния вертикального сплиттера
                    right_state_hex = data.get("right_splitter_state", "")
                    if right_state_hex and hasattr(self, "right_splitter"):
                        self.right_splitter.restoreState(QByteArray.fromHex(right_state_hex.encode('utf-8')))
            except Exception:
                pass

    def center_on_screen(self) -> None:
        """Центрирует окно приложения на первичном экране."""
        screen = QApplication.primaryScreen().geometry()
        width = 1100
        height = 720
        x = (screen.width() - width) // 2
        y = (screen.height() - height) // 2
        self.setGeometry(x, y, width, height)

    def load_locale(self, lang: str) -> None:
        if getattr(sys, "frozen", False):
            locales_dir = Path(sys._MEIPASS) / "locales"
        else:
            locales_dir = Path(__file__).resolve().parents[2] / "locales"
            
        locale_file = locales_dir / f"{lang}.json"
        if locale_file.exists():
            try:
                with open(locale_file, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
            except Exception:
                self.translations = {}
        else:
            self.translations = {}

    def loc(self, key: str, *args) -> str:
        val = self.translations.get(key, key)
        if args:
            try:
                return val.format(*args)
            except Exception:
                pass
        return val

    def change_language(self, lang: str) -> None:
        self.current_lang = lang
        self.load_locale(lang)
        
        inp = self.input_entry.text()
        out = self.output_entry.text()
        
        if inp in ["Введите путь для папки Dicom_input", "Enter path for Dicom_input folder"]:
            self.input_entry.setText(self.loc("placeholder_input"))
        if out in ["Введите путь для папки Dicom_output", "Enter path for Dicom_output folder"]:
            self.output_entry.setText(self.loc("placeholder_output"))
            
        self.update_locale_texts()
        self.save_last_paths()
        
        # Синхронизируем положение переключателя
        if hasattr(self, "lang_switch"):
            self.lang_switch.lang = lang
            self.lang_switch.update_slider_position()

    def update_locale_texts(self) -> None:
        self.setWindowTitle(self.loc("title"))
        self.title_label.setText(self.loc("title_label"))
        self.input_label.setText(self.loc("input_folder"))
        self.output_label.setText(self.loc("output_folder"))
        self.btn_browse_in.setText(self.loc("browse"))
        self.btn_browse_out.setText(self.loc("browse"))
        self.settings_title.setText(self.loc("optimization_params"))
        
        if hasattr(self, "theme_combo"):
            self.theme_combo.blockSignals(True)
            self.theme_combo.clear()
            self.theme_combo.addItem(self.loc("theme_dark"), "dark")
            self.theme_combo.addItem(self.loc("theme_light"), "light")
            self.theme_combo.addItem(self.loc("theme_red"), "red")
            self.theme_combo.addItem(self.loc("theme_sunset"), "sunset")
            self.theme_combo.addItem(self.loc("theme_cyber"), "cyber")
            index = self.theme_combo.findData(self.current_theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)
        
        self.cb_new_uids.setText(self.loc("generate_uids"))
        self.cb_split_mf.setText(self.loc("split_multiframe"))
        self.cb_clean_tags.setText(self.loc("clean_tags"))
        self.cb_default_tags.setText(self.loc("fill_mandatory"))
        self.cb_explicit_vr.setText(self.loc("write_explicit"))
        self.cb_exclude_reports.setText(self.loc("exclude_reports"))
        self.cb_split_series.setText(self.loc("split_series"))
        
        self.sidebar_title.setText(self.loc("patient_explorer"))
        self.scan_btn.setText(self.loc("scan_input"))
        self.log_title.setText(self.loc("log_title"))
        
        # Tooltips
        self.btn_create_in.setToolTip(self.loc("tooltip_create_input"))
        self.btn_create_out.setToolTip(self.loc("tooltip_create_output"))
        self.btn_open_in.setToolTip(self.loc("tooltip_open_input"))
        self.btn_open_out.setToolTip(self.loc("tooltip_open_output"))

        if hasattr(self, "viewer_panel"):
            self.viewer_panel.retranslate_ui()
            if hasattr(self.viewer_panel, "viewer"):
                self.viewer_panel.viewer.update()

        self.update_selection_label()

        if self.is_processing:
            if self.stop_event.is_set():
                self.start_btn.setText(self.loc("status_stopping"))
            else:
                self.start_btn.setText(self.loc("stop_optimization"))
        else:
            self.start_btn.setText(self.loc("run_optimization"))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_dark_titlebar(self)

    def closeEvent(self, event) -> None:
        self.save_last_paths()
        super().closeEvent(event)

    def create_widgets(self) -> None:
        # Главный контейнер
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Создаем разделитель (splitter)
        self.splitter = CustomSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("leftSplitter")

        # ----------------------------------------------------
        # 1. Левая боковая панель (Проводник пациентов)
        # ----------------------------------------------------
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("sidebar")
        self.sidebar_frame.setMinimumWidth(0) # Позволяет сжимать до 0
        self.sidebar_frame.setMaximumWidth(450) # Ограничивает максимальную ширину дерева при ресайзе
        
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(15, 15, 20, 15)
        sidebar_layout.setSpacing(10)

        # Заголовок боковой панели и кнопка "Сканировать"
        title_layout = QHBoxLayout()
        self.sidebar_title = QLabel()
        self.sidebar_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        title_layout.addWidget(self.sidebar_title)

        self.scan_btn = QPushButton()
        self.scan_btn.clicked.connect(self.run_input_scan)
        self.scan_btn.setStyleSheet("font-weight: bold; min-width: 90px;")
        title_layout.addWidget(self.scan_btn)
        
        sidebar_layout.addLayout(title_layout)

        # Дерево QTreeWidget
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.itemChanged.connect(self.on_item_changed)
        self.tree_widget.itemClicked.connect(self.on_item_clicked)
        sidebar_layout.addWidget(self.tree_widget)

        # Метка статуса выбора
        self.selection_label = QLabel()
        self.selection_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #A0A0A0;")
        sidebar_layout.addWidget(self.selection_label)

        self.splitter.addWidget(self.sidebar_frame)

        # ----------------------------------------------------
        # 2. Правая основная панель
        # ----------------------------------------------------
        self.content_frame = QFrame()
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(20, 15, 20, 15)
        content_layout.setSpacing(12)

        # Верхняя панель (Заголовок и Языковой переключатель)
        top_layout = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #FFFFFF;")
        top_layout.addWidget(self.title_label)

        # Выпадающий список выбора цветовой темы
        self.theme_combo = QComboBox(self.content_frame)
        self.theme_combo.setFixedWidth(120)
        self.theme_combo.activated.connect(self.on_theme_changed)
        top_layout.addWidget(self.theme_combo)

        # Слайдер переключения языков
        resources_dir = self.project_root / "themes"
        self.lang_switch = LanguageSwitch(self.content_frame, self.change_language, self.current_lang, resources_dir)
        top_layout.addWidget(self.lang_switch)
        
        content_layout.addLayout(top_layout)

        # Создаем вертикальный разделитель для правой панели
        self.right_splitter = CustomSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setObjectName("rightSplitter")

        # Группа 1: Выбор папок
        folder_frame = QFrame()
        folder_frame.setObjectName("groupFrame")
        folder_layout = QGridLayout(folder_frame)
        folder_layout.setContentsMargins(15, 15, 15, 15)
        folder_layout.setSpacing(10)

        # Иконки кнопок папок
        self.img_create = QIcon(str(resources_dir / "create_folder.png"))
        self.img_open_in = QIcon(str(resources_dir / "open_folder_input.png"))
        self.img_open_out = QIcon(str(resources_dir / "open_folder_output.png"))

        # Папка ввода
        self.btn_create_in = QPushButton()
        self.btn_create_in.setIcon(self.img_create)
        self.btn_create_in.setFixedSize(30, 30)
        self.btn_create_in.clicked.connect(lambda: self.ask_and_create_folder("input"))
        folder_layout.addWidget(self.btn_create_in, 0, 0)

        self.input_label = QLabel()
        self.input_label.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        folder_layout.addWidget(self.input_label, 0, 1)

        self.input_entry = QLineEdit()
        self.input_entry.setText(self.saved_input_path)
        folder_layout.addWidget(self.input_entry, 0, 2)

        self.btn_open_in = QPushButton()
        self.btn_open_in.setIcon(self.img_open_in)
        self.btn_open_in.setFixedSize(30, 30)
        self.btn_open_in.clicked.connect(self.open_input_dir)
        folder_layout.addWidget(self.btn_open_in, 0, 3)

        self.btn_browse_in = QPushButton()
        self.btn_browse_in.clicked.connect(self.browse_input)
        self.btn_browse_in.setFixedWidth(100)
        folder_layout.addWidget(self.btn_browse_in, 0, 4)

        # Папка вывода
        self.btn_create_out = QPushButton()
        self.btn_create_out.setIcon(self.img_create)
        self.btn_create_out.setFixedSize(30, 30)
        self.btn_create_out.clicked.connect(lambda: self.ask_and_create_folder("output"))
        folder_layout.addWidget(self.btn_create_out, 1, 0)

        self.output_label = QLabel()
        self.output_label.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        folder_layout.addWidget(self.output_label, 1, 1)

        self.output_entry = QLineEdit()
        self.output_entry.setText(self.saved_output_path)
        folder_layout.addWidget(self.output_entry, 1, 2)

        self.btn_open_out = QPushButton()
        self.btn_open_out.setIcon(self.img_open_out)
        self.btn_open_out.setFixedSize(30, 30)
        self.btn_open_out.clicked.connect(self.open_output_dir)
        folder_layout.addWidget(self.btn_open_out, 1, 3)

        self.btn_browse_out = QPushButton()
        self.btn_browse_out.clicked.connect(self.browse_output)
        self.btn_browse_out.setFixedWidth(100)
        folder_layout.addWidget(self.btn_browse_out, 1, 4)



        # Группа 2: Настройки оптимизации
        settings_frame = QFrame()
        settings_frame.setObjectName("groupFrame")
        settings_layout = QGridLayout(settings_frame)
        settings_layout.setContentsMargins(15, 15, 15, 15)
        settings_layout.setSpacing(10)

        self.settings_title = QLabel()
        self.settings_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        settings_layout.addWidget(self.settings_title, 0, 0, 1, 2)

        self.cb_new_uids = QCheckBox()
        self.cb_new_uids.setChecked(True)
        settings_layout.addWidget(self.cb_new_uids, 1, 0)

        self.cb_split_mf = QCheckBox()
        self.cb_split_mf.setChecked(True)
        settings_layout.addWidget(self.cb_split_mf, 1, 1)

        self.cb_clean_tags = QCheckBox()
        self.cb_clean_tags.setChecked(True)
        settings_layout.addWidget(self.cb_clean_tags, 2, 0)

        self.cb_default_tags = QCheckBox()
        self.cb_default_tags.setChecked(True)
        settings_layout.addWidget(self.cb_default_tags, 2, 1)

        self.cb_explicit_vr = QCheckBox()
        self.cb_explicit_vr.setChecked(True)
        settings_layout.addWidget(self.cb_explicit_vr, 3, 0)

        self.cb_exclude_reports = QCheckBox()
        self.cb_exclude_reports.setChecked(True)
        settings_layout.addWidget(self.cb_exclude_reports, 3, 1)

        self.cb_split_series = QCheckBox()
        self.cb_split_series.setChecked(True)
        settings_layout.addWidget(self.cb_split_series, 4, 0)



        # Группа 3: Лог выполнения
        log_frame = QFrame()
        log_frame.setObjectName("groupFrame")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(15, 15, 15, 15)
        log_layout.setSpacing(8)

        self.log_title = QLabel()
        self.log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        log_layout.addWidget(self.log_title)

        self.log_textbox = QTextEdit()
        self.log_textbox.setReadOnly(True)
        self.log_textbox.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self.log_textbox)

        # Добавляем элементы в вертикальный разделитель по очереди
        self.right_splitter.addWidget(folder_frame)
        self.right_splitter.addWidget(settings_frame)
        self.right_splitter.addWidget(log_frame)

        content_layout.addWidget(self.right_splitter)

        # Группа 4: Прогресс и Кнопка пуска
        control_frame = QFrame()
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(24)
        control_layout.addWidget(self.progress_bar)

        self.start_btn = QPushButton()
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self.start_processing)
        control_layout.addWidget(self.start_btn)

        content_layout.addWidget(control_frame)

        # Оборачиваем правую часть в QStackedWidget для переключения вьюера
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.content_frame) # Страница 0
        
        self.viewer_panel = DicomViewerPanel(self)
        self.viewer_panel.close_requested.connect(self.close_viewer)
        self.right_stack.addWidget(self.viewer_panel) # Страница 1
        
        self.splitter.addWidget(self.right_stack)
        main_layout.addWidget(self.splitter)

        # Настройки сплиттеров
        self.splitter.setCollapsible(0, True)   # Дерево может быть скрыто полностью
        self.splitter.setCollapsible(1, False)  # Главную панель скрывать нельзя
        self.splitter.setSizes([385, 715])      # Пропорции по умолчанию (385px ширина дерева)
        self.splitter.setStretchFactor(0, 1)    # Дерево проводника растягивается при увеличении окна
        self.splitter.setStretchFactor(1, 0)    # Правая область сохраняет свой размер

        self.right_splitter.setCollapsible(0, True)  # Папки можно скрыть
        self.right_splitter.setCollapsible(1, True)  # Настройки можно скрыть
        self.right_splitter.setCollapsible(2, True)  # Лог можно скрыть
        
        # Настройка растяжения: папки и настройки не растягиваются, лог растягивается
        self.right_splitter.setStretchFactor(0, 0)
        self.right_splitter.setStretchFactor(1, 0)
        self.right_splitter.setStretchFactor(2, 1)

        self.right_splitter.setSizes([90, 135, 245])     # Размеры по умолчанию

    def apply_styles(self) -> None:
        if not hasattr(self, "current_theme") or self.current_theme not in self.THEMES:
            self.current_theme = "dark"
            
        palette = self.THEMES[self.current_theme]
        
        arrow_right, arrow_down = self.generate_theme_arrows(palette['TEXT_LIGHT'], palette['ACCENT_COLOR'])
        chk_checked = (self.project_root / "themes" / "checkbox_checked.png").as_posix()
        splitter_dots_v = (self.project_root / "themes" / "splitter_dots_v.png").as_posix()
        splitter_dots_h = (self.project_root / "themes" / "splitter_dots_h.png").as_posix()

        qss = f"""
            QMainWindow {{
                background-color: {palette['MAIN_BG']};
            }}
            QDialog {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
            }}
            QWidget {{
                color: {palette['TEXT_COLOR']};
                font-family: "Segoe UI", Arial, sans-serif;
            }}
            #sidebar {{
                background-color: {palette['PANEL_BG']};
                border-right: 1px solid {palette['BORDER_COLOR']};
            }}
            #groupFrame {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                border-radius: 8px;
            }}
            QTreeWidget {{
                background-color: {palette['MAIN_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                border-radius: 6px;
                padding: 5px;
            }}
            QTreeView::branch,
            QTreeWidget::branch {{
                background-color: transparent;
                border-image: none;
                image: none;
            }}
            QTreeView::branch:has-children:closed,
            QTreeView::branch:has-children:closed:has-siblings,
            QTreeWidget::branch:has-children:closed,
            QTreeWidget::branch:has-children:closed:has-siblings {{
                border-image: none;
                image: url(PATH_ARROW_RIGHT);
            }}
            QTreeView::branch:has-children:open,
            QTreeView::branch:has-children:open:has-siblings,
            QTreeWidget::branch:has-children:open,
            QTreeWidget::branch:has-children:open:has-siblings {{
                border-image: none;
                image: url(PATH_ARROW_DOWN);
            }}
            QTreeWidget::indicator, QTreeView::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {palette['BORDER_COLOR_ALT']};
                border-radius: 3px;
                background-color: {palette['MAIN_BG']};
            }}
            QTreeWidget::indicator:hover, QTreeView::indicator:hover {{
                border-color: {palette['ACCENT_COLOR']};
            }}
            QTreeWidget::indicator:checked, QTreeView::indicator:checked {{
                background-color: {palette['ACCENT_COLOR_DARK']};
                border-color: {palette['ACCENT_COLOR_DARK']};
                image: url(PATH_CHECKBOX_CHECKED);
            }}
            QTreeWidget::indicator:unchecked, QTreeView::indicator:unchecked {{
                background-color: {palette['MAIN_BG']};
                border-color: {palette['BORDER_COLOR_ALT']};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {palette['MAIN_BG']};
                width: 10px;
                margin: 0px 0px 0px 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {palette['BUTTON_HOVER_BG']};
                min-height: 20px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {palette['BORDER_COLOR_ALT']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                border: none;
                background: {palette['MAIN_BG']};
                height: 10px;
                margin: 0px 0px 0px 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {palette['BUTTON_HOVER_BG']};
                min-width: 20px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {palette['BORDER_COLOR_ALT']};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                border: none;
                background: none;
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
            QTreeWidget::item {{
                padding: 6px 4px;
                color: {palette['TEXT_COLOR']};
            }}
            QTreeWidget::item:hover {{
                background-color: {palette['BUTTON_BG']};
                border-radius: 4px;
            }}
            QTreeWidget::item:selected {{
                background-color: {palette['ACCENT_COLOR']};
                color: #FFFFFF;
                border-radius: 4px;
            }}
            QPushButton {{
                background-color: {palette['BUTTON_BG']};
                border: 1px solid {palette['BORDER_COLOR_ALT']};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                color: {palette['TEXT_COLOR']};
            }}
            QPushButton:hover {{
                background-color: {palette['BUTTON_HOVER_BG']};
                border-color: {palette['BORDER_COLOR_ALT']};
            }}
            QPushButton:pressed {{
                background-color: {palette['BUTTON_PRESSED_BG']};
            }}
            QPushButton#startBtn {{
                background-color: {palette['ACCENT_COLOR_DARK']};
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
                border: none;
            }}
            QPushButton#startBtn:hover {{
                background-color: {palette['ACCENT_COLOR']};
            }}
            QPushButton#startBtn:pressed {{
                background-color: {palette['ACCENT_COLOR_DEEP']};
            }}
            QPushButton#stopBtn {{
                background-color: #EF4444;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
                border: none;
            }}
            QPushButton#stopBtn:hover {{
                background-color: #F87171;
            }}
            QPushButton#stopBtn:pressed {{
                background-color: #B91C1C;
            }}
            QLineEdit {{
                background-color: {palette['MAIN_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                border-radius: 6px;
                padding: 6px 10px;
                color: {palette['TEXT_COLOR']};
            }}
            QLineEdit:focus {{
                border-color: {palette['ACCENT_COLOR']};
            }}
            QTextEdit {{
                background-color: {palette['MAIN_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                border-radius: 6px;
                color: {palette['TEXT_COLOR']};
            }}
            QProgressBar {{
                background-color: {palette['PROGRESS_BG']};
                border: 1px solid {palette['PROGRESS_BORDER']};
                border-radius: 6px;
                text-align: center;
                color: {palette['TEXT_COLOR']};
                font-weight: bold;
                font-size: 11px;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 {palette['GRADIENT_START']}, stop:1 {palette['GRADIENT_END']});
                border-radius: 5px;
            }}
            QCheckBox {{
                spacing: 8px;
                color: {palette['TEXT_COLOR']};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {palette['BORDER_COLOR_ALT']};
                border-radius: 4px;
                background-color: {palette['MAIN_BG']};
            }}
            QCheckBox::indicator:hover {{
                border-color: {palette['ACCENT_COLOR']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {palette['ACCENT_COLOR_DARK']};
                border-color: {palette['ACCENT_COLOR_DARK']};
            }}
            QSplitter::handle {{
                background-color: {palette['SPLITTER_COLOR']};
            }}
            QSplitter::handle:horizontal {{
                width: 3px;
                image: url(PATH_SPLITTER_DOTS_V);
            }}
            QSplitter::handle:vertical {{
                height: 3px;
                image: url(PATH_SPLITTER_DOTS_H);
            }}
            QSplitter::handle:hover {{
                background-color: {palette['ACCENT_COLOR']};
            }}
            QSplitter#rightSplitter::handle {{
                background-color: transparent;
            }}
            QSplitter#rightSplitter::handle:vertical {{
                height: 8px;
                image: none;
            }}
            QSplitter#rightSplitter::handle:hover {{
                background-color: transparent;
            }}
            QSplitter#leftSplitter::handle {{
                background-color: transparent;
            }}
            QSplitter#leftSplitter::handle:horizontal {{
                width: 8px;
                image: none;
            }}
            QSplitter#leftSplitter::handle:hover {{
                background-color: transparent;
            }}
            QToolTip {{
                background-color: {palette['PANEL_BG']};
                color: {palette['TEXT_COLOR']};
                border: 1px solid {palette['BORDER_COLOR_ALT']};
                border-radius: 4px;
                padding: 4px;
            }}
            QComboBox {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR_ALT']};
                border-radius: 6px;
                padding: 4px 10px;
                color: {palette['TEXT_COLOR']};
                min-width: 80px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: url(PATH_ARROW_DOWN);
                width: 12px;
                height: 12px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                selection-background-color: {palette['ACCENT_COLOR']};
                selection-color: #FFFFFF;
                outline: none;
            }}
        """.replace("PATH_ARROW_RIGHT", arrow_right)\
           .replace("PATH_ARROW_DOWN", arrow_down)\
           .replace("PATH_CHECKBOX_CHECKED", chk_checked)\
           .replace("PATH_SPLITTER_DOTS_V", splitter_dots_v)\
           .replace("PATH_SPLITTER_DOTS_H", splitter_dots_h)

        QApplication.instance().setStyleSheet(qss)
        
        self.sidebar_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {palette['TEXT_LIGHT']};")
        self.selection_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {palette['TEXT_MUTED']};")
        self.title_label.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {palette['TEXT_LIGHT']};")
        if hasattr(self, "input_label"):
            self.input_label.setStyleSheet(f"font-weight: bold; color: {palette['TEXT_LIGHT']};")
        if hasattr(self, "output_label"):
            self.output_label.setStyleSheet(f"font-weight: bold; color: {palette['TEXT_LIGHT']};")
        if hasattr(self, "settings_title"):
            self.settings_title.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {palette['TEXT_LIGHT']};")
        if hasattr(self, "log_title"):
            self.log_title.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {palette['TEXT_LIGHT']};")
        if hasattr(self, "lbl_status"):
            self.lbl_status.setStyleSheet(f"font-size: 13px; color: {palette['TEXT_COLOR']};")
            
        if hasattr(self, "lang_switch"):
            self.lang_switch.apply_theme()
            
        if hasattr(self, "viewer_panel"):
            self.viewer_panel.apply_theme()

    # Drag and Drop поддержка перетаскивания папок (включая сетевые) в любую часть окна
    def install_drag_drop_filters(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if hasattr(event, "mimeData") and event.mimeData().hasUrls():
                urls = event.mimeData().urls()
                if urls:
                    local_path = Path(urls[0].toLocalFile())
                    if local_path.is_dir():
                        event.acceptProposedAction()
                        return True
        elif event.type() == QEvent.Type.Drop:
            if hasattr(event, "mimeData") and event.mimeData().hasUrls():
                urls = event.mimeData().urls()
                if urls:
                    local_path = Path(urls[0].toLocalFile())
                    if local_path.is_dir():
                        self.input_entry.setText(str(local_path.resolve()))
                        self.save_last_paths()
                        event.acceptProposedAction()
                        return True
        return super().eventFilter(watched, event)

    # Методы обзора и открытия папок
    def browse_input(self) -> None:
        initial = self.input_entry.text()
        if "Введите путь" in initial or "Enter path" in initial:
            initial = ""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Input Directory", initial)
        if dir_path:
            self.input_entry.setText(str(Path(dir_path).resolve()))
            self.save_last_paths()

    def browse_output(self) -> None:
        initial = self.output_entry.text()
        if "Введите путь" in initial or "Enter path" in initial:
            initial = ""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", initial)
        if dir_path:
            self.output_entry.setText(str(Path(dir_path).resolve()))
            self.save_last_paths()

    def open_input_dir(self) -> None:
        inp_dir = self.input_entry.text()
        if "Введите путь" in inp_dir or "Enter path" in inp_dir:
            self.bridge.log_signal.emit(self.loc("error_input_path_not_set"), "error")
            return
            
        path = Path(inp_dir)
        if path.exists():
            import os
            os.startfile(path)
        else:
            self.bridge.log_signal.emit(self.loc("error_input_not_exist_warning", path), "warning")

    def open_output_dir(self) -> None:
        out_dir = self.output_entry.text()
        if "Введите путь" in out_dir or "Enter path" in out_dir:
            self.bridge.log_signal.emit(self.loc("error_output_path_not_set"), "error")
            return
            
        path = Path(out_dir)
        if path.exists():
            import os
            os.startfile(path)
        else:
            self.bridge.log_signal.emit(self.loc("error_output_not_exist", path), "warning")

    def ask_and_create_folder(self, dir_type: str) -> None:
        folder_name = "Dicom_input" if dir_type == "input" else "Dicom_output"
        message = self.loc("ask_create_folder", folder_name)
        
        dialog = CustomQuestionDialog(self, self.loc("dialog_title"), message)
        dialog.exec()
        result = dialog.result_value
        
        if not result or result == "no":
            return
            
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path(__file__).resolve().parents[2]
            
        input_path = app_dir / "Dicom_input"
        output_path = app_dir / "Dicom_output"
        
        if result == "yes":
            target_path = input_path if dir_type == "input" else output_path
            try:
                target_path.mkdir(parents=True, exist_ok=True)
                if dir_type == "input":
                    self.input_entry.setText(str(target_path.resolve()))
                else:
                    self.output_entry.setText(str(target_path.resolve()))
                self.bridge.log_signal.emit(self.loc("folder_created", target_path.resolve()), "success")
            except Exception as e:
                self.bridge.log_signal.emit(self.loc("error_create_folder", e), "error")
                
        elif result == "both":
            try:
                input_path.mkdir(parents=True, exist_ok=True)
                output_path.mkdir(parents=True, exist_ok=True)
                self.input_entry.setText(str(input_path.resolve()))
                self.output_entry.setText(str(output_path.resolve()))
                self.bridge.log_signal.emit(self.loc("folders_created_both", input_path.resolve(), output_path.resolve()), "success")
            except Exception as e:
                self.bridge.log_signal.emit(self.loc("error_create_folders_both", e), "error")
                
        self.save_last_paths()

    # Методы обработки сигналов от процессора
    def add_log(self, text: str, tag: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = "white"
        if tag == "warning":
            color = "#ffb347"
        elif tag == "error":
            color = "#ff6961"
        elif tag == "success":
            color = "#77dd77"
        formatted_text = f"<span style='color:#a0a0a0;'>[{timestamp}]</span> <span style='color:{color};'>{text}</span>"
        self.log_textbox.append(formatted_text)
        self.log_textbox.moveCursor(QTextCursor.MoveOperation.End)

    def update_progress(self, current: int, total: int) -> None:
        if total > 0:
            prog = current / total
            pct = int(prog * 100)
            self.progress_bar.setValue(pct)

    def update_scan_progress(self, current: int, total: int) -> None:
        if self.scan_dialog:
            self.scan_dialog.update_progress(current, total)

    def on_processing_finished(self) -> None:
        self.is_processing = False
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setText(self.loc("run_optimization"))
        self.start_btn.setEnabled(True)
        self.apply_styles() # Обновит стиль (вернет синий цвет кнопки)
        self.set_gui_enabled(True)
        self.log_textbox.moveCursor(QTextCursor.MoveOperation.End)

    def on_tree_scanned(self, tree_data: dict) -> None:
        self.populate_tree(tree_data)
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(self.loc("scan_input"))
        self.update_selection_label()
        if self.scan_dialog:
            self.scan_dialog.accept()
            self.scan_dialog = None

    def set_gui_enabled(self, enabled: bool) -> None:
        self.start_btn.setEnabled(enabled)

    # Работа с QTreeWidget
    def populate_tree(self, tree_data: dict) -> None:
        self._is_updating_tree = True
        self.tree_widget.clear()
        
        for (pat_name, pat_id), studies in sorted(tree_data.items(), key=lambda x: str(x[0])):
            # Пациент
            pat_label = f"{pat_name} [{pat_id}]"
            pat_item = QTreeWidgetItem(self.tree_widget)
            pat_item.setText(0, pat_label)
            pat_item.setCheckState(0, Qt.CheckState.Checked)
            pat_item.setData(0, Qt.ItemDataRole.UserRole, ("patient", pat_name, pat_id))
            
            for (study_date, study_desc, study_uid), series_dict in sorted(studies.items(), key=lambda x: str(x[0])):
                # Исследование
                study_label = f"{study_date} - {study_desc}" if study_date else study_desc
                study_item = QTreeWidgetItem(pat_item)
                study_item.setText(0, study_label)
                study_item.setCheckState(0, Qt.CheckState.Checked)
                study_item.setData(0, Qt.ItemDataRole.UserRole, ("study", study_uid))
                
                for (series_label, s_uid, seg_idx), files in sorted(series_dict.items(), key=lambda x: str(x[0])):
                    # Серия
                    series_item = QTreeWidgetItem(study_item)
                    series_item.setText(0, series_label)
                    series_item.setCheckState(0, Qt.CheckState.Checked)
                    # Сохраняем информацию о файлах серии
                    series_item.setData(0, Qt.ItemDataRole.UserRole, ("series", s_uid, seg_idx, files))

        self.tree_widget.expandAll()
        self.tree_widget.resizeColumnToContents(0)
        needed_width = self.tree_widget.columnWidth(0) + 60
        needed_width = max(220, min(needed_width, 600))
        sizes = self.splitter.sizes()
        if len(sizes) >= 2:
            total = sum(sizes)
            sizes[0] = needed_width
            sizes[1] = total - needed_width
            self.splitter.setSizes(sizes)
        self._is_updating_tree = False

    def on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Обрабатывает клик на элемент дерева. Если кликнули на серию - открывает/закрывает вьюер."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, tuple):
            return
            
        if data[0] == "series":
            s_uid = data[1]
            seg_idx = data[2]
            files = data[3]
            
            # Если вьюер уже открыт для этой же серии, закрываем его
            if self.viewer_active and self.current_view_series_uid == s_uid and self.current_view_seg_idx == seg_idx:
                self.close_viewer()
            else:
                self.open_viewer(s_uid, seg_idx, files)

    def open_viewer(self, s_uid: str, seg_idx: int, files: list[str]) -> None:
        """Переключает правую панель на вьюер и загружает серию."""
        self.viewer_active = True
        self.current_view_series_uid = s_uid
        self.current_view_seg_idx = seg_idx
        
        self.viewer_panel.load_series(files)
        self.right_stack.setCurrentIndex(1) # Переключаем на страницу вьюера

    def close_viewer(self) -> None:
        """Сворачивает вьюер и возвращает исходный интерфейс."""
        self.viewer_active = False
        self.current_view_series_uid = None
        self.current_view_seg_idx = None
        
        # Сбрасываем инструменты вьюера и скрываем hu_panel
        self.viewer_panel.viewer.ruler_active = False
        self.viewer_panel.viewer.hu_active = False
        if hasattr(self.viewer_panel, "hu_panel"):
            self.viewer_panel.hu_panel.hide()
        self.viewer_panel.update_buttons_style()
        
        self.right_stack.setCurrentIndex(0) # Переключаем на исходный интерфейс
        self.tree_widget.clearSelection()   # Снимаем выделение в дереве

    def on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._is_updating_tree:
            return
        
        self._is_updating_tree = True
        try:
            state = item.checkState(0)
            self._set_children_state(item, state)
            self._update_parent_states(item)
        finally:
            self._is_updating_tree = False
        
        self.update_selection_label()

    def _set_children_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._set_children_state(child, state)

    def _update_parent_states(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        if not parent:
            return
            
        checked_count = 0
        unchecked_count = 0
        
        for i in range(parent.childCount()):
            child = parent.child(i)
            c_state = child.checkState(0)
            if c_state == Qt.CheckState.Checked:
                checked_count += 1
            elif c_state == Qt.CheckState.Unchecked:
                unchecked_count += 1
                
        if checked_count == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Checked)
        elif unchecked_count == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
            
        self._update_parent_states(parent)

    def get_selected_files(self) -> list:
        selected_files = []
        for i in range(self.tree_widget.topLevelItemCount()):
            pat_item = self.tree_widget.topLevelItem(i)
            for j in range(pat_item.childCount()):
                study_item = pat_item.child(j)
                for k in range(study_item.childCount()):
                    series_item = study_item.child(k)
                    if series_item.checkState(0) == Qt.CheckState.Checked:
                        data = series_item.data(0, Qt.ItemDataRole.UserRole)
                        if data and data[0] == "series":
                            selected_files.extend(data[3])
        return selected_files

    def get_patient_nodes_data(self) -> list:
        nodes = []
        for i in range(self.tree_widget.topLevelItemCount()):
            pat_item = self.tree_widget.topLevelItem(i)
            data = pat_item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "patient":
                nodes.append((pat_item, data[1], data[2])) # item, name, id
        return nodes

    def update_selection_label(self) -> None:
        selected_files = self.get_selected_files()
        
        total_patients = self.tree_widget.topLevelItemCount()
        total_studies = 0
        total_series = 0
        total_files_count = 0
        
        for i in range(total_patients):
            pat_item = self.tree_widget.topLevelItem(i)
            total_studies += pat_item.childCount()
            for j in range(pat_item.childCount()):
                study_item = pat_item.child(j)
                total_series += study_item.childCount()
                for k in range(study_item.childCount()):
                    series_item = study_item.child(k)
                    data = series_item.data(0, Qt.ItemDataRole.UserRole)
                    if data and data[0] == "series":
                        total_files_count += len(data[3])
                        
        text = self.loc("selected_status", len(selected_files), total_files_count, total_patients, total_studies, total_series)
        self.selection_label.setText(text)

    # Запуск сканирования входной папки
    def run_input_scan(self) -> None:
        input_path = self.input_entry.text()
        if not input_path or "Введите путь" in input_path or "Enter path" in input_path:
            return

        path = Path(input_path)
        if not path.exists():
            return

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(self.loc("tree_loading"))
        self.selection_label.setText(self.loc("tree_loading"))
        
        self.scan_stop_event = threading.Event()
        self.scan_dialog = ScanProgressDialog(self, self.scan_stop_event)
        
        threading.Thread(target=self._scan_thread, args=(path, self.scan_stop_event), daemon=True).start()
        self.scan_dialog.exec()

    def _scan_thread(self, path: Path, stop_event: threading.Event) -> None:
        temp_config = ProcessingConfig(
            new_uids=False, split_multiframe=False, clean_tags=False,
            default_tags=False, explicit_vr=False, exclude_reports=False,
            split_series=self.cb_split_series.isChecked()
        )
        logger = QtLogger(self.bridge)
        processor = DicomProcessor(path, self.output_entry.text(), temp_config, logger, stop_event, lang=self.current_lang)
        
        try:
            tree_data = processor.scan_input_directory()
            self.bridge.tree_scanned_signal.emit(tree_data)
        except Exception as e:
            self.bridge.log_signal.emit(f"Error scanning directory: {e}", "error")
            self.bridge.tree_scanned_signal.emit({})

    def get_selected_files_or_autoscan(self) -> list:
        selected_files = self.get_selected_files()
        if not selected_files and self.tree_widget.topLevelItemCount() == 0:
            self.run_input_scan()
            selected_files = self.get_selected_files()
        return selected_files

    # Главный поток обработки
    def start_processing(self) -> None:
        if self.is_processing:
            self.stop_event.set()
            self.start_btn.setText(self.loc("status_stopping"))
            self.start_btn.setEnabled(False)
            return

        input_raw = self.input_entry.text()
        output_raw = self.output_entry.text()

        if ("Введите путь" in input_raw or "Enter path" in input_raw or 
            "Введите путь" in output_raw or "Enter path" in output_raw):
            self.add_log(self.loc('error_paths_not_set'), "error")
            return

        input_dir = Path(input_raw)
        output_dir = Path(output_raw)

        if not input_dir.exists():
            self.add_log(self.loc('error_input_not_exist', input_dir), "error")
            return

        # Определяем, скрыто ли дерево (первая секция горизонтального сплиттера)
        is_tree_hidden = (self.splitter.sizes()[0] <= 5)

        patient_overrides = {}
        if is_tree_hidden:
            selected_files = None
        else:
            selected_files = self.get_selected_files_or_autoscan()
            if not selected_files:
                self.add_log(self.loc('tree_empty'), "error")
                return

            # Интерактивная валидация данных пациента (только если дерево не скрыто)
            patient_nodes = self.get_patient_nodes_data()
            for p_item, pat_name, pat_id in patient_nodes:
                any_selected = False
                for j in range(p_item.childCount()):
                    study_item = p_item.child(j)
                    for k in range(study_item.childCount()):
                        series_item = study_item.child(k)
                        if series_item.checkState(0) == Qt.CheckState.Checked:
                            any_selected = True
                            break
                if not any_selected:
                    continue

                is_valid = True
                if not pat_name or pat_name.strip() == "" or pat_name.upper() == "UNKNOWN":
                    is_valid = False
                if not pat_id or pat_id.strip() == "" or pat_id.upper() == "UNKNOWN":
                    is_valid = False
                if len(pat_name) > 64 or len(pat_id) > 64:
                    is_valid = False

                if not is_valid:
                    dialog = PatientEditDialog(self, pat_name, pat_id)
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        new_name = dialog.new_name.strip()
                        new_id = dialog.new_id.strip()
                        if new_name and new_id:
                            patient_overrides[(pat_name, pat_id)] = (new_name, new_id)

        self.is_processing = True
        self.stop_event.clear()
        
        self.start_btn.setObjectName("stopBtn")
        self.start_btn.setText(self.loc("stop_optimization"))
        self.apply_styles() # Обновит стиль (сделает кнопку красной)
        
        self.progress_bar.setValue(0)
        self.log_textbox.clear()

        config = ProcessingConfig(
            new_uids=self.cb_new_uids.isChecked(),
            split_multiframe=self.cb_split_mf.isChecked(),
            clean_tags=self.cb_clean_tags.isChecked(),
            default_tags=self.cb_default_tags.isChecked(),
            explicit_vr=self.cb_explicit_vr.isChecked(),
            exclude_reports=self.cb_exclude_reports.isChecked(),
            split_series=self.cb_split_series.isChecked()
        )

        logger = QtLogger(self.bridge)
        processor = DicomProcessor(
            input_dir, output_dir, config, logger, self.stop_event, 
            lang=self.current_lang, selected_files=selected_files,
            patient_overrides=patient_overrides
        )

        threading.Thread(
            target=self._run_processor, 
            args=(processor,), 
            daemon=True
        ).start()

    def _run_processor(self, processor: DicomProcessor) -> None:
        try:
            processor.process()
        finally:
            self.bridge.finished_signal.emit()
