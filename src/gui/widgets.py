import math
import io
from pathlib import Path
import numpy as np
import pydicom

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QRect, QPointF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QComboBox, QSlider, QApplication, QSplitter, QSplitterHandle
)
from PyQt6.QtGui import (
    QIcon, QFont, QPixmap, QBrush, QColor, QPainter,
    QPen, QImage, QLinearGradient, QPolygon
)


class LanguageSwitch(QFrame):
    """Кастомный горизонтальный переключатель языков с флагами."""

    def __init__(self, parent: QWidget, command=None, current_lang: str = "ru", resources_dir: Path = None) -> None:
        super().__init__(parent)
        self.command = command
        self.lang = current_lang
        
        self.setFixedSize(76, 30)
        self.setStyleSheet("""
            QFrame {
                background-color: #2D2D2D;
                border: 1px solid #4B5563;
                border-radius: 15px;
            }
        """)

        # Загружаем картинки флагов
        self.px_ru = QPixmap(str(resources_dir / "ru_flag.png"))
        self.px_gb = QPixmap(str(resources_dir / "gb_flag.png"))

        # Метка RU флага (слева)
        self.lbl_ru = QLabel(self)
        self.lbl_ru.setPixmap(self.px_ru)
        self.lbl_ru.setScaledContents(True)
        self.lbl_ru.setFixedSize(24, 16)
        self.lbl_ru.move(9, 7)
        self.lbl_ru.setStyleSheet("background: transparent; border: none;")

        # Метка GB флага (справа)
        self.lbl_gb = QLabel(self)
        self.lbl_gb.setPixmap(self.px_gb)
        self.lbl_gb.setScaledContents(True)
        self.lbl_gb.setFixedSize(24, 16)
        self.lbl_gb.move(43, 7)
        self.lbl_gb.setStyleSheet("background: transparent; border: none;")

        # Ползунок (slider)
        self.slider = QFrame(self)
        self.slider.setFixedSize(36, 24)
        self.slider.setStyleSheet("""
            QFrame {
                background-color: #4B5563;
                border: none;
                border-radius: 12px;
            }
        """)

        self.slider_img = QLabel(self.slider)
        self.slider_img.setScaledContents(True)
        self.slider_img.setFixedSize(24, 16)
        self.slider_img.move(6, 4)
        self.slider_img.setStyleSheet("background: transparent; border: none;")

        self.update_slider_position()

    def update_slider_position(self) -> None:
        if self.lang == "ru":
            self.slider.move(3, 3)
            self.slider_img.setPixmap(self.px_ru)
        else:
            self.slider.move(37, 3)
            self.slider_img.setPixmap(self.px_gb)

    def apply_theme(self) -> None:
        main_win = self.window()
        if hasattr(main_win, "current_theme") and hasattr(main_win, "THEMES"):
            palette = main_win.THEMES[main_win.current_theme]
            frame_bg = palette["PANEL_BG"]
            frame_border = palette["BORDER_COLOR_ALT"]
            slider_bg = palette["BUTTON_HOVER_BG"]
        else:
            frame_bg = "#2D2D2D"
            frame_border = "#4B5563"
            slider_bg = "#4B5563"
            
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {frame_bg};
                border: 1px solid {frame_border};
                border-radius: 15px;
            }}
        """)
        self.slider.setStyleSheet(f"""
            QFrame {{
                background-color: {slider_bg};
                border: none;
                border-radius: 12px;
            }}
        """)

    def mousePressEvent(self, event) -> None:
        if self.lang == "ru":
            self.lang = "en"
        else:
            self.lang = "ru"
        self.update_slider_position()
        if self.command:
            self.command(self.lang)



class HUVerticalSlider(QWidget):
    """Кастомный вертикальный слайдер с двумя ползунками для Window/Level (HU) в стиле Varian Eclipse."""
    values_changed = pyqtSignal(float, float)  # lower_val, upper_val

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.min_hu = -1000.0
        self.max_hu = 3000.0
        self.lower_val = -160.0
        self.upper_val = 240.0
        
        self.pad = 12
        self.bar_width = 10
        self.slider_size = 14
        
        self.dragging = None  # None, 'lower', 'upper', 'both'
        self.drag_start_y = 0
        self.drag_start_lower = 0.0
        self.drag_start_upper = 0.0

        self.setMinimumWidth(60)
        self.setMouseTracking(True)

    def set_values(self, lower: float, upper: float) -> None:
        lower = max(self.min_hu, min(self.max_hu, lower))
        upper = max(self.min_hu, min(self.max_hu, upper))
        if lower > upper:
            lower, upper = upper, lower
        if upper - lower < 1.0:
            upper = lower + 1.0
        self.lower_val = lower
        self.upper_val = upper
        self.update()

    def _hu_to_y(self, hu: float) -> int:
        h = self.height()
        active_h = h - 2 * self.pad
        if active_h <= 0:
            return self.pad
        val_pct = (hu - self.min_hu) / (self.max_hu - self.min_hu)
        return int(self.pad + active_h * (1.0 - val_pct))

    def _y_to_hu(self, y: int) -> float:
        h = self.height()
        active_h = h - 2 * self.pad
        if active_h <= 0:
            return self.min_hu
        val_pct = 1.0 - (y - self.pad) / active_h
        val_pct = max(0.0, min(1.0, val_pct))
        return self.min_hu + val_pct * (self.max_hu - self.min_hu)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        h = self.height()
        w = self.width()
        cx = w // 2 - 12  # Сдвигаем шкалу чуть влево, чтобы подписи влезли справа

        # 1. Рисуем фон шкалы
        bar_rect = QRect(cx - self.bar_width // 2, self.pad, self.bar_width, h - 2 * self.pad)
        painter.setPen(QPen(QColor("#374151"), 1))
        painter.setBrush(QBrush(QColor("#111827")))
        painter.drawRect(bar_rect)

        # 2. Рисуем градиент внутри шкалы (от lower_val до upper_val)
        y_lower = self._hu_to_y(self.lower_val)
        y_upper = self._hu_to_y(self.upper_val)
        
        # Заливка ниже нижнего порога (черный цвет)
        if y_lower < h - self.pad:
            rect_below = QRect(bar_rect.x(), y_lower, bar_rect.width(), h - self.pad - y_lower)
            painter.fillRect(rect_below, QColor("#000000"))

        # Заливка выше верхнего порога (белый цвет)
        if y_upper > self.pad:
            rect_above = QRect(bar_rect.x(), self.pad, bar_rect.width(), y_upper - self.pad)
            painter.fillRect(rect_above, QColor("#FFFFFF"))

        # Градиент между порогами (от черного снизу до белого сверху)
        if y_upper < y_lower:
            grad = QLinearGradient(cx, y_lower, cx, y_upper)
            grad.setColorAt(0.0, QColor("#000000"))
            grad.setColorAt(1.0, QColor("#FFFFFF"))
            rect_grad = QRect(bar_rect.x(), y_upper, bar_rect.width(), y_lower - y_upper)
            painter.fillRect(rect_grad, grad)

        # 3. Рисуем деления (риски)
        painter.setPen(QPen(QColor("#4B5563"), 1))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        for hu in range(int(self.min_hu), int(self.max_hu) + 1, 500):
            y_tick = self._hu_to_y(hu)
            painter.drawLine(cx - self.bar_width // 2 - 2, y_tick, cx - self.bar_width // 2, y_tick)
            
            # Подписи (каждые 1000 HU)
            if hu % 1000 == 0:
                painter.setPen(QPen(QColor("#9CA3AF"), 1))
                painter.drawText(cx + self.bar_width // 2 + 5, y_tick + 3, str(hu))
                painter.setPen(QPen(QColor("#4B5563"), 1))

        # 4. Рисуем ползунки (треугольники слева от шкалы, указывающие вправо)
        y_u = self._hu_to_y(self.upper_val)
        y_l = self._hu_to_y(self.lower_val)

        # Рисуем ползунок Upper
        up_poly = [
            QPoint(cx - self.bar_width // 2 - 12, y_u - 5),
            QPoint(cx - self.bar_width // 2 - 2, y_u),
            QPoint(cx - self.bar_width // 2 - 12, y_u + 5)
        ]
        painter.setPen(QPen(QColor("#60A5FA") if self.dragging == "upper" else QColor("#D1D5DB"), 1.5))
        painter.setBrush(QBrush(QColor("#3B82F6") if self.dragging == "upper" else QColor("#4B5563")))
        painter.drawPolygon(QPolygon(up_poly))

        # Рисуем ползунок Lower
        low_poly = [
            QPoint(cx - self.bar_width // 2 - 12, y_l - 5),
            QPoint(cx - self.bar_width // 2 - 2, y_l),
            QPoint(cx - self.bar_width // 2 - 12, y_l + 5)
        ]
        painter.setPen(QPen(QColor("#60A5FA") if self.dragging == "lower" else QColor("#D1D5DB"), 1.5))
        painter.setBrush(QBrush(QColor("#3B82F6") if self.dragging == "lower" else QColor("#4B5563")))
        painter.drawPolygon(QPolygon(low_poly))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            y = event.position().y()
            w = self.width()
            cx = w // 2 - 12
            
            y_u = self._hu_to_y(self.upper_val)
            y_l = self._hu_to_y(self.lower_val)
            
            click_x = event.position().x()
            in_slider_x = (cx - self.bar_width // 2 - 15 <= click_x <= cx - self.bar_width // 2)

            if in_slider_x and abs(y - y_u) < 8:
                self.dragging = 'upper'
            elif in_slider_x and abs(y - y_l) < 8:
                self.dragging = 'lower'
            elif click_x >= cx - self.bar_width // 2 - 4 and click_x <= cx + self.bar_width // 2 + 4 and y_u <= y <= y_l:
                self.dragging = 'both'
                self.drag_start_y = y
                self.drag_start_lower = self.lower_val
                self.drag_start_upper = self.upper_val
            else:
                new_hu = self._y_to_hu(y)
                if abs(new_hu - self.upper_val) < abs(new_hu - self.lower_val):
                    self.dragging = 'upper'
                    self.upper_val = max(self.lower_val + 10.0, new_hu)
                else:
                    self.dragging = 'lower'
                    self.lower_val = min(self.upper_val - 10.0, new_hu)
                self.values_changed.emit(self.lower_val, self.upper_val)
            self.update()

    def mouseMoveEvent(self, event) -> None:
        y = event.position().y()
        if self.dragging == 'upper':
            new_hu = self._y_to_hu(y)
            self.upper_val = max(self.lower_val + 10.0, min(self.max_hu, new_hu))
            self.values_changed.emit(self.lower_val, self.upper_val)
            self.update()
        elif self.dragging == 'lower':
            new_hu = self._y_to_hu(y)
            self.lower_val = min(self.upper_val - 10.0, max(self.min_hu, new_hu))
            self.values_changed.emit(self.lower_val, self.upper_val)
            self.update()
        elif self.dragging == 'both':
            hu_start = self._y_to_hu(self.drag_start_y)
            hu_current = self._y_to_hu(y)
            delta_hu = hu_current - hu_start
            
            new_lower = self.drag_start_lower + delta_hu
            new_upper = self.drag_start_upper + delta_hu
            
            if new_lower < self.min_hu:
                diff = self.min_hu - new_lower
                new_lower += diff
                new_upper += diff
            elif new_upper > self.max_hu:
                diff = new_upper - self.max_hu
                new_lower -= diff
                new_upper -= diff
                
            self.lower_val = max(self.min_hu, min(self.max_hu, new_lower))
            self.upper_val = max(self.min_hu, min(self.max_hu, new_upper))
            self.values_changed.emit(self.lower_val, self.upper_val)
            self.update()
        else:
            w = self.width()
            cx = w // 2 - 12
            y_u = self._hu_to_y(self.upper_val)
            y_l = self._hu_to_y(self.lower_val)
            click_x = event.position().x()
            in_slider_x = (cx - self.bar_width // 2 - 15 <= click_x <= cx - self.bar_width // 2)
            
            if in_slider_x and (abs(y - y_u) < 8 or abs(y - y_l) < 8):
                self.setCursor(Qt.CursorShape.SplitVCursor)
            elif click_x >= cx - self.bar_width // 2 and click_x <= cx + self.bar_width // 2 and y_u <= y <= y_l:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        self.dragging = None
        self.update()



class DicomViewerWidget(QWidget):
    """Виджет для отрисовки DICOM-изображения и линейки."""
    slice_scrolled = pyqtSignal(int)  # -1 или 1 для прокрутки колесиком мыши
    window_changed = pyqtSignal(float, float) # новые window_width, window_center

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.current_pixmap = None
        self.current_dataset = None
        self.image_rect = None

        # Сведения о срезах для OSD-оверлея
        self.current_slice = 0
        self.total_slices = 0

        # Параметры окна HU
        self.window_width = 400.0
        self.window_center = 40.0

        # Управление зумом и панорамированием
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        self.last_mouse_pos = None

        # Режимы работы левой кнопки мыши
        self.ruler_active = False
        self.hu_active = False

        # Состояния рисования линейки
        self.start_pos = None
        self.current_pos = None
        self.drawing_line = False
        self.ruler_close_rect = None

        # Состояние изменения окна
        self.windowing_active = False

        # Состояние панорамирования (Pan)
        self.pan_active = False

        self.osd_visible = True

        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #000000;")

    def set_osd_visible(self, visible: bool) -> None:
        self.osd_visible = visible
        self.update()

    def set_dicom_image(self, pixmap: QPixmap, ds) -> None:
        self.current_pixmap = pixmap
        self.current_dataset = ds
        self.update()

    def set_window_params(self, width: float, center: float) -> None:
        self.window_width = width
        self.window_center = center
        self.update()

    def set_slice_info(self, current: int, total: int) -> None:
        self.current_slice = current
        self.total_slices = total
        self.update()

    def clear_viewer(self) -> None:
        self.current_pixmap = None
        self.current_dataset = None
        self.start_pos = None
        self.current_pos = None
        self.drawing_line = False
        self.ruler_close_rect = None
        self.windowing_active = False
        self.pan_active = False
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        self.current_slice = 0
        self.total_slices = 0
        self.update()

    def mousePressEvent(self, event) -> None:
        if not self.current_pixmap:
            return

        btn = event.button()
        pos = event.position()

        # Проверяем клик по крестику закрытия линейки
        if btn == Qt.MouseButton.LeftButton and self.ruler_active and self.ruler_close_rect and self.ruler_close_rect.contains(pos.toPoint()):
            self.start_pos = None
            self.current_pos = None
            self.drawing_line = False
            self.ruler_close_rect = None
            self.update()
            return

        if btn in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            # Панорамирование (Pan) при зажатии средней или правой кнопки мыши
            self.pan_active = True
            self.last_mouse_pos = event.position()
        elif btn == Qt.MouseButton.LeftButton:
            if self.ruler_active:
                # Рисование линейки
                self.start_pos = event.position()
                self.current_pos = event.position()
                self.drawing_line = True
                self.update()
            elif self.hu_active:
                # Изменение окна HU
                self.windowing_active = True
                self.last_mouse_pos = event.position()

    def mouseMoveEvent(self, event) -> None:
        if self.pan_active and self.last_mouse_pos:
            delta = event.position() - self.last_mouse_pos
            self.pan_offset += delta
            self.last_mouse_pos = event.position()
            self.update()
        elif self.drawing_line:
            self.current_pos = event.position()
            self.update()
        elif self.windowing_active and self.last_mouse_pos:
            delta = event.position() - self.last_mouse_pos
            self.last_mouse_pos = event.position()
            
            # По горизонтали меняем ширину окна (Width), по вертикали - уровень (Center)
            self.window_width = max(1.0, self.window_width + delta.x() * 2.0)
            self.window_center = self.window_center + delta.y() * 2.0
            self.window_changed.emit(self.window_width, self.window_center)

    def mouseReleaseEvent(self, event) -> None:
        btn = event.button()
        if btn in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self.pan_active = False
        elif btn == Qt.MouseButton.LeftButton:
            if self.drawing_line:
                self.current_pos = event.position()
                self.drawing_line = False
                self.update()
            elif self.windowing_active:
                self.windowing_active = False

    def wheelEvent(self, event) -> None:
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # Масштабирование по Ctrl + колесо мыши
            delta = event.angleDelta().y()
            if delta > 0:
                # Колесо вперед (от себя) -> уменьшение
                self.zoom_factor = max(0.1, self.zoom_factor - 0.1)
            elif delta < 0:
                # Колесо назад (на себя) -> увеличение
                self.zoom_factor = min(10.0, self.zoom_factor + 0.1)
            self.update()
        else:
            # Обычная прокрутка колесиком -> смена срезов
            delta = event.angleDelta().y()
            if delta > 0:
                self.slice_scrolled.emit(-1)
            elif delta < 0:
                self.slice_scrolled.emit(1)

    def to_image_coords(self, pt: QPointF) -> tuple[float, float]:
        if not self.image_rect or not self.current_pixmap:
            return 0.0, 0.0

        x_w = pt.x()
        y_w = pt.y()

        offset_x = self.image_rect.x()
        offset_y = self.image_rect.y()
        view_w = self.image_rect.width()
        view_h = self.image_rect.height()

        pix_w = self.current_pixmap.width()
        pix_h = self.current_pixmap.height()

        x_img = (x_w - offset_x) * (pix_w / view_w)
        y_img = (y_w - offset_y) * (pix_h / view_h)

        x_img = max(0.0, min(float(pix_w), x_img))
        y_img = max(0.0, min(float(pix_h), y_img))

        return x_img, y_img

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))

        if self.current_pixmap:
            pix_w = self.current_pixmap.width()
            pix_h = self.current_pixmap.height()
            w = self.width()
            h = self.height()

            scale = min(w / pix_w, h / pix_h) * self.zoom_factor
            view_w = int(pix_w * scale)
            view_h = int(pix_h * scale)

            # Центр виджета + смещение панорамирования
            offset_x = (w - view_w) // 2 + int(self.pan_offset.x())
            offset_y = (h - view_h) // 2 + int(self.pan_offset.y())

            self.image_rect = QRect(offset_x, offset_y, view_w, view_h)
            painter.drawPixmap(self.image_rect, self.current_pixmap)

            # Отрисовка измерительной линейки
            if self.ruler_active and self.start_pos and self.current_pos:
                pen = QPen(QColor("#10B981"), 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.drawLine(self.start_pos.toPoint(), self.current_pos.toPoint())

                self.draw_tick(painter, self.start_pos, self.current_pos)
                self.draw_tick(painter, self.current_pos, self.start_pos)

                x1, y1 = self.to_image_coords(self.start_pos)
                x2, y2 = self.to_image_coords(self.current_pos)

                row_spacing = 1.0
                col_spacing = 1.0
                if self.current_dataset:
                    pixel_spacing = getattr(self.current_dataset, "PixelSpacing", None)
                    if pixel_spacing and len(pixel_spacing) == 2:
                        row_spacing = float(pixel_spacing[0])
                        col_spacing = float(pixel_spacing[1])
                    else:
                        imager_spacing = getattr(self.current_dataset, "ImagerPixelSpacing", None)
                        if imager_spacing and len(imager_spacing) == 2:
                            row_spacing = float(imager_spacing[0])
                            col_spacing = float(imager_spacing[1])

                dx = (x2 - x1) * col_spacing
                dy = (y2 - y1) * row_spacing
                dist_mm = math.sqrt(dx * dx + dy * dy)
                unit = self.parent().parent_app.loc("mm") if hasattr(self, "parent") and hasattr(self.parent(), "parent_app") else "mm"
                text_dist = f"{dist_mm:.1f} {unit}"
                mid_x = (self.start_pos.x() + self.current_pos.x()) / 2
                mid_y = (self.start_pos.y() + self.current_pos.y()) / 2

                font = QFont("Consolas", 10, QFont.Weight.Bold)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                rect_dist = metrics.boundingRect(text_dist)

                padding_x = 4
                padding_y = 2
                cross_width = 12
                space = 6

                total_w = rect_dist.width() + cross_width + space
                total_h = max(rect_dist.height(), cross_width)

                rect_plate = QRect(
                    int(mid_x - total_w / 2 - padding_x),
                    int(mid_y - 15 - total_h / 2 - padding_y),
                    int(total_w + padding_x * 2),
                    int(total_h + padding_y * 2)
                )

                # Рисуем подложку
                painter.fillRect(rect_plate, QColor(0, 0, 0, 180))

                # Рисуем текст
                painter.setPen(QColor("#FFFFFF"))
                text_rect = QRect(
                    rect_plate.x() + padding_x,
                    rect_plate.y() + padding_y,
                    rect_dist.width(),
                    total_h
                )
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text_dist)

                # Рисуем крестик [X]
                cross_rect = QRect(
                    text_rect.x() + text_rect.width() + space,
                    rect_plate.y() + (rect_plate.height() - cross_width) // 2,
                    cross_width,
                    cross_width
                )
                self.ruler_close_rect = cross_rect

                pen_cross = QPen(QColor("#EF4444"), 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen_cross)
                margin = 2
                painter.drawLine(
                    cross_rect.x() + margin, cross_rect.y() + margin,
                    cross_rect.x() + cross_rect.width() - margin, cross_rect.y() + cross_rect.height() - margin
                )
                painter.drawLine(
                    cross_rect.x() + cross_rect.width() - margin, cross_rect.y() + margin,
                    cross_rect.x() + margin, cross_rect.y() + cross_rect.height() - margin
                )
            else:
                self.ruler_close_rect = None

            # Отрисовка метаданных пациента/серии в левом верхнем углу (OSD)
            if self.osd_visible:
                if self.current_dataset:
                    painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                    
                    pat_name = str(getattr(self.current_dataset, "PatientName", "Unknown"))
                    pat_id = str(getattr(self.current_dataset, "PatientID", "Unknown"))
                    
                    # Форматируем дату рождения
                    dob_raw = getattr(self.current_dataset, "PatientBirthDate", "")
                    dob = ""
                    if dob_raw and len(dob_raw) == 8:
                        dob = f"{dob_raw[6:8]}-{dob_raw[4:6]}-{dob_raw[0:4]}"
                    else:
                        dob = dob_raw
                    sex = getattr(self.current_dataset, "PatientSex", "")
                    pat_info = f"{dob} {sex}".strip()
                    
                    study_desc = getattr(self.current_dataset, "StudyDescription", "")
                    series_desc = getattr(self.current_dataset, "SeriesDescription", "")
                    
                    top_lines = [pat_name, pat_id, pat_info, study_desc, series_desc]
                    top_lines = [line for line in top_lines if line] # убираем пустые
                    
                    y_offset = 15
                    for line in top_lines:
                        metrics = painter.fontMetrics()
                        rect_line = metrics.boundingRect(line)
                        rect_line.moveTopLeft(QPoint(15, y_offset))
                        painter.fillRect(rect_line.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                        painter.setPen(QColor("#E5E7EB"))
                        painter.drawText(rect_line, Qt.AlignmentFlag.AlignLeft, line)
                        y_offset += rect_line.height() + 5

                # Вывод параметров окна HU, Zoom, Modality и Transfer Syntax в левый нижний угол
                painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                
                lines_bottom = []
                lines_bottom.append(f"WL: {int(self.window_center)} WW: {int(self.window_width)} | Zoom: {int(self.zoom_factor * 100)}%")
                
                if self.current_dataset:
                    modality = getattr(self.current_dataset, "Modality", "")
                    if modality:
                        lines_bottom.append(f"Modality: {modality}")
                    
                    try:
                        ts_uid = getattr(self.current_dataset, "original_transfer_syntax", None)
                        if not ts_uid:
                            ts_uid = self.current_dataset.file_meta.TransferSyntaxUID
                        ts_name = ts_uid.name
                        if " (" in ts_name:
                            ts_name = ts_name.split(" (")[0]
                        lines_bottom.append(f"TS: {ts_name}")
                    except Exception:
                        pass

                metrics_b = painter.fontMetrics()
                y_offset_b = self.height() - 15
                for line in reversed(lines_bottom):
                    rect_info = metrics_b.boundingRect(line)
                    rect_info.moveBottomLeft(QPoint(15, y_offset_b))
                    painter.fillRect(rect_info.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                    painter.setPen(QColor("#E5E7EB"))
                    painter.drawText(rect_info, Qt.AlignmentFlag.AlignLeft, line)
                    y_offset_b -= rect_info.height() + 5

                # Отрисовка номера среза в правом нижнем углу
                if self.total_slices > 0:
                    painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
                    slice_info = ""
                    if hasattr(self, "parent") and hasattr(self.parent(), "parent_app"):
                        slice_info = self.parent().parent_app.loc("viewer_slice", self.current_slice, self.total_slices)
                    else:
                        slice_info = f"Slice: {self.current_slice} / {self.total_slices}"
                    
                    spacing_text = ""
                    if self.current_dataset:
                        spacing = getattr(self.current_dataset, "SliceThickness", None)
                        if spacing is None:
                            spacing = getattr(self.current_dataset, "SpacingBetweenSlices", None)
                        if spacing is not None:
                            try:
                                spacing_val = float(spacing)
                                if hasattr(self, "parent") and hasattr(self.parent(), "parent_app"):
                                    spacing_text = self.parent().parent_app.loc("viewer_spacing", spacing_val)
                                else:
                                    spacing_text = f"Spacing: {spacing_val:.1f} mm"
                            except (ValueError, TypeError):
                                pass

                    metrics_r = painter.fontMetrics()
                    
                    # Рисуем номер среза
                    rect_slice = metrics_r.boundingRect(slice_info)
                    rect_slice.moveBottomRight(QPoint(self.width() - 15, self.height() - 15))
                    painter.fillRect(rect_slice.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                    painter.setPen(QColor("#E5E7EB"))
                    painter.drawText(rect_slice, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, slice_info)
                    
                    # Рисуем шаг среза над номером среза
                    if spacing_text:
                        rect_spacing = metrics_r.boundingRect(spacing_text)
                        rect_spacing.moveBottomRight(QPoint(self.width() - 15, rect_slice.top() - 8))
                        painter.fillRect(rect_spacing.adjusted(-4, -2, 4, 2), QColor(0, 0, 0, 150))
                        painter.setPen(QColor("#E5E7EB"))
                        painter.drawText(rect_spacing, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, spacing_text)

    def draw_tick(self, painter: QPainter, pt1: QPointF, pt2: QPointF) -> None:
        dx = pt2.x() - pt1.x()
        dy = pt2.y() - pt1.y()
        length = math.sqrt(dx*dx + dy*dy)
        if length < 1.0:
            return
        px = -dy / length
        py = dx / length
        
        tick_len = 8
        p1 = QPoint(int(pt1.x() + px * tick_len), int(pt1.y() + py * tick_len))
        p2 = QPoint(int(pt1.x() - px * tick_len), int(pt1.y() - py * tick_len))
        painter.drawLine(p1, p2)



class DicomViewerPanel(QWidget):
    """Панель управления просмотром DICOM серий."""
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.sorted_files = []
        self.current_index = -1
        self.is_loading = False

        # Параметры окна по умолчанию
        self.window_width = 400.0
        self.window_center = 40.0
        self.default_wc = 40.0
        self.default_ww = 400.0

        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 0)
        layout.setSpacing(6)

        # 1.  Верхняя панель (Информация о серии, Кнопка линейки, Кнопка HU, Выбор пресетов, Кнопка закрыть)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        self.lbl_info = QLabel(self)
        self.lbl_info.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        self.lbl_info.hide() # Скрываем, так как информация теперь выводится на оверлее вьюера
        top_layout.addWidget(self.lbl_info)

        top_layout.addStretch()

        # Выпадающий список пресетов HU
        self.cb_presets = QComboBox(self)
        self.cb_presets.setFixedWidth(200)
        self.cb_presets.setStyleSheet("""
            QComboBox {
                background-color: #2A2A2A;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #FFFFFF;
                padding: 0px 8px;
                font-size: 12px;
                min-height: 28px;
                max-height: 28px;
            }
            QComboBox QAbstractItemView {
                background-color: #1A1A1A;
                border: 1px solid #374151;
                color: #FFFFFF;
                selection-background-color: #3B82F6;
            }
        """)
        top_layout.addWidget(self.cb_presets)

        # Загружаем монохромные PNG иконки
        resources_dir = self.parent_app.project_root / "themes"
        self.img_ruler = QIcon(str(resources_dir / "ruler.png"))
        self.img_hu = QIcon(str(resources_dir / "hu.png"))
        self.img_osd = QIcon(str(resources_dir / "eye.png"))
        self.img_close = QIcon(str(resources_dir / "close.png"))

        # Кнопка линейки
        self.btn_ruler = QPushButton(self)
        self.btn_ruler.setIcon(self.img_ruler)
        self.btn_ruler.setIconSize(QSize(20, 20))
        self.btn_ruler.setFixedSize(28, 28)
        self.btn_ruler.setToolTip(self.parent_app.loc("tooltip_ruler") if hasattr(self.parent_app, "loc") else "Линейка")
        self.btn_ruler.clicked.connect(self.toggle_ruler)
        top_layout.addWidget(self.btn_ruler)

        # Кнопка настройки HU
        self.btn_hu = QPushButton(self)
        self.btn_hu.setIcon(self.img_hu)
        self.btn_hu.setIconSize(QSize(20, 20))
        self.btn_hu.setFixedSize(28, 28)
        self.btn_hu.setToolTip(self.parent_app.loc("tooltip_hu") if hasattr(self.parent_app, "loc") else "Настройка окна HU")
        self.btn_hu.clicked.connect(self.toggle_hu)
        top_layout.addWidget(self.btn_hu)

        # Кнопка скрытия надписей OSD
        self.btn_osd = QPushButton(self)
        self.btn_osd.setIcon(self.img_osd)
        self.btn_osd.setIconSize(QSize(20, 20))
        self.btn_osd.setFixedSize(28, 28)
        self.btn_osd.setToolTip(self.parent_app.loc("tooltip_osd") if hasattr(self.parent_app, "loc") else "Показать/скрыть надписи")
        self.btn_osd.clicked.connect(self.toggle_osd)
        top_layout.addWidget(self.btn_osd)

        # Кнопка закрытия
        self.btn_close = QPushButton(self)
        self.btn_close.setIcon(self.img_close)
        self.btn_close.setIconSize(QSize(20, 20))
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setToolTip(self.parent_app.loc("tooltip_close_viewer") if hasattr(self.parent_app, "loc") else "Закрыть просмотр")
        self.btn_close.clicked.connect(self.close_requested.emit)
        top_layout.addWidget(self.btn_close)
        
        layout.addLayout(top_layout)

        # 2.  Центральная область (Изображение и шкала HU справа)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)

        self.viewer = DicomViewerWidget(self)
        self.viewer.slice_scrolled.connect(self.on_slice_scrolled)
        self.viewer.window_changed.connect(self.on_window_changed)
        main_layout.addWidget(self.viewer, stretch=1)

        # Создаем и добавляем шкалу HU справа
        self.setup_hu_panel()
        main_layout.addWidget(self.hu_panel)

        layout.addLayout(main_layout)

        # 2.5 Горизонтальный слайдер срезов снизу
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.valueChanged.connect(self.on_slider_changed)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #1F2937;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3B82F6;
                width: 30px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #60A5FA;
            }
        """)
        layout.addWidget(self.slider)

        # Инициализируем локализованные пресеты
        self.update_buttons_style()
        self.retranslate_ui()
        self.cb_presets.currentIndexChanged.connect(self.apply_preset)

    def setup_hu_panel(self) -> None:
        self.hu_panel = QFrame(self)
        self.hu_panel.setFixedWidth(70)
        self.hu_panel.setStyleSheet("""
            QFrame {
                background-color: #1F2937;
                border: 1px solid #374151;
                border-radius: 6px;
            }
            QLabel {
                border: none;
                background: transparent;
                color: #EF4444;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        panel_layout = QVBoxLayout(self.hu_panel)
        panel_layout.setContentsMargins(4, 10, 4, 10)
        panel_layout.setSpacing(6)

        self.lbl_upper_hu = QLabel("240 HU", self.hu_panel)
        self.lbl_upper_hu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self.lbl_upper_hu)

        self.hu_slider = HUVerticalSlider(self.hu_panel)
        self.hu_slider.values_changed.connect(self.on_vertical_slider_changed)
        panel_layout.addWidget(self.hu_slider, stretch=1)

        self.lbl_lower_hu = QLabel("-160 HU", self.hu_panel)
        self.lbl_lower_hu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel_layout.addWidget(self.lbl_lower_hu)

        self.hu_panel.hide()

    def on_vertical_slider_changed(self, lower: float, upper: float) -> None:
        self.window_width = upper - lower
        self.window_center = (upper + lower) / 2.0
        
        # Сбрасываем выбранный пресет при ручной регулировке шкалы
        self.cb_presets.blockSignals(True)
        self.cb_presets.setCurrentIndex(-1)
        self.cb_presets.blockSignals(False)
        
        self.lbl_upper_hu.setText(f"{int(upper)} HU")
        self.lbl_lower_hu.setText(f"{int(lower)} HU")
        self.update_current_slice_pixels()

    def retranslate_ui(self) -> None:
        self.cb_presets.blockSignals(True)
        self.cb_presets.clear()
        self.cb_presets.addItem(self.parent_app.loc("preset_dicom"), "dicom")
        self.cb_presets.addItem(self.parent_app.loc("preset_soft"), "soft")
        self.cb_presets.addItem(self.parent_app.loc("preset_bone"), "bone")
        self.cb_presets.addItem(self.parent_app.loc("preset_lung"), "lung")
        self.cb_presets.addItem(self.parent_app.loc("preset_brain"), "brain")
        self.cb_presets.blockSignals(False)

        self.btn_ruler.setToolTip(self.parent_app.loc("tooltip_ruler") if hasattr(self.parent_app, "loc") else "Линейка")
        self.btn_hu.setToolTip(self.parent_app.loc("tooltip_hu") if hasattr(self.parent_app, "loc") else "Настройка окна HU")
        self.btn_osd.setToolTip(self.parent_app.loc("tooltip_osd") if hasattr(self.parent_app, "loc") else "Показать/скрыть надписи")
        self.btn_close.setToolTip(self.parent_app.loc("tooltip_close_viewer") if hasattr(self.parent_app, "loc") else "Закрыть просмотр")

    def apply_theme(self) -> None:
        if not hasattr(self, "parent_app") or not hasattr(self.parent_app, "current_theme"):
            return
        palette = self.parent_app.THEMES[self.parent_app.current_theme]
        
        self.lbl_info.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {palette['TEXT_LIGHT']};")
        
        self.cb_presets.setStyleSheet(f"""
            QComboBox {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR_ALT']};
                color: {palette['TEXT_COLOR']};
                selection-background-color: {palette['ACCENT_COLOR']};
                selection-color: #FFFFFF;
            }}
            QComboBox QAbstractItemView {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                selection-background-color: {palette['ACCENT_COLOR']};
                selection-color: #FFFFFF;
                outline: none;
            }}
        """)
        
        self.hu_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {palette['PANEL_BG']};
                border: 1px solid {palette['BORDER_COLOR']};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
                color: {palette['TEXT_COLOR']};
            }}
        """)

        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {palette['BORDER_COLOR_ALT']};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {palette['ACCENT_COLOR']};
                width: 30px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {palette['ACCENT_COLOR_DARK']};
            }}
        """)
        
        self.update_buttons_style()

    def update_buttons_style(self) -> None:
        palette = self.parent_app.THEMES[self.parent_app.current_theme] if hasattr(self, "parent_app") and hasattr(self.parent_app, "current_theme") else {
            "ACCENT_COLOR": "#3B82F6",
            "ACCENT_COLOR_DARK": "#2563EB",
            "BUTTON_BG": "#374151",
            "BORDER_COLOR_ALT": "#4B5563",
            "BUTTON_HOVER_BG": "#4B5563"
        }
        
        accent_color = palette.get("ACCENT_COLOR", "#3B82F6")
        accent_dark = palette.get("ACCENT_COLOR_DARK", "#2563EB")
        
        btn_bg = palette.get("BUTTON_BG", "#374151")
        btn_border = palette.get("BORDER_COLOR_ALT", "#4B5563")
        btn_hover = palette.get("BUTTON_HOVER_BG", "#4B5563")

        style_ruler_active = f"""
            QPushButton {{
                background-color: {accent_color};
                border: 1px solid {accent_dark};
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }}
        """
        style_ruler_inactive = f"""
            QPushButton {{
                background-color: {btn_bg};
                border: 1px solid {btn_border};
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }}
            QPushButton:hover {{ background-color: {btn_hover}; }}
        """
        style_hu_active = f"""
            QPushButton {{
                background-color: {accent_color};
                border: 1px solid {accent_dark};
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }}
        """
        style_hu_inactive = f"""
            QPushButton {{
                background-color: {btn_bg};
                border: 1px solid {btn_border};
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }}
            QPushButton:hover {{ background-color: {btn_hover}; }}
        """
        style_osd_active = f"""
            QPushButton {{
                background-color: {accent_color};
                border: 1px solid {accent_dark};
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }}
        """
        style_osd_inactive = f"""
            QPushButton {{
                background-color: {btn_bg};
                border: 1px solid {btn_border};
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }}
            QPushButton:hover {{ background-color: {btn_hover}; }}
        """
        style_close = """
            QPushButton {
                background-color: #BE123C;
                border: 1px solid #E11D48;
                border-radius: 4px;
                padding: 0px;
                min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
            }
            QPushButton:hover {
                background-color: #E11D48;
                border-color: #F43F5E;
            }
            QPushButton:pressed {
                background-color: #9F1239;
            }
        """

        self.btn_ruler.setStyleSheet(style_ruler_active if self.viewer.ruler_active else style_ruler_inactive)
        self.btn_hu.setStyleSheet(style_hu_active if self.viewer.hu_active else style_hu_inactive)
        self.btn_osd.setStyleSheet(style_osd_active if self.viewer.osd_visible else style_osd_inactive)
        self.btn_close.setStyleSheet(style_close)

    def toggle_osd(self) -> None:
        self.viewer.set_osd_visible(not self.viewer.osd_visible)
        self.update_buttons_style()

    def toggle_ruler(self) -> None:
        active = not self.viewer.ruler_active
        self.viewer.ruler_active = active
        if active:
            self.viewer.hu_active = False
            if hasattr(self, "hu_panel"):
                self.hu_panel.hide()
        self.update_buttons_style()

    def toggle_hu(self) -> None:
        active = not self.viewer.hu_active
        self.viewer.hu_active = active
        if active:
            self.viewer.ruler_active = False
            if hasattr(self, "hu_panel"):
                self.hu_panel.show()
        else:
            if hasattr(self, "hu_panel"):
                self.hu_panel.hide()
        self.update_buttons_style()

    def load_series(self, files: list[str]) -> None:
        import pydicom
        self.is_loading = True
        self.sorted_files = []
        self.current_index = -1
        self.viewer.clear_viewer()

        # По умолчанию сбрасываем пресеты в "dicom"
        self.cb_presets.blockSignals(True)
        self.cb_presets.setCurrentIndex(0)
        self.cb_presets.blockSignals(False)

        slices = []
        for f in files:
            try:
                # Быстрое сканирование тегов для сортировки
                ds = pydicom.dcmread(f, stop_before_pixels=True)
                
                ipp = getattr(ds, "ImagePositionPatient", None)
                z_coord = float(ipp[2]) if ipp and len(ipp) >= 3 else 0.0
                instance_number = int(getattr(ds, "InstanceNumber", 0))
                slices.append((f, z_coord, instance_number))
            except Exception:
                pass

        if not slices:
            self.lbl_info.setText("Серия не содержит корректных DICOM файлов.")
            self.viewer.set_slice_info(0, 0)
            self.is_loading = False
            return

        # Сортируем срезы по Z-координате
        slices.sort(key=lambda x: (x[1], x[2]))
        self.sorted_files = [x[0] for x in slices]

        self.slider.setRange(0, len(self.sorted_files) - 1)
        self.is_loading = False
        
        self.set_current_slice(0)

    def read_truncated_dicom(self, filepath: str):
        import pydicom
        import io
        import numpy as np
        
        # Сначала читаем метаданные с stop_before_pixels=True, чтобы узнать Transfer Syntax и размер
        ds_meta = pydicom.dcmread(filepath, stop_before_pixels=True)
        transfer_syntax = ds_meta.file_meta.TransferSyntaxUID
        
        with open(filepath, "rb") as f:
            file_bytes = bytearray(f.read())
            
        # Определяем, сжатый ли формат пикселей
        is_compressed = transfer_syntax.startswith("1.2.840.10008.1.2.4.") or "rle" in getattr(ds_meta.file_meta, "TransferSyntaxUID_name", "").lower()
        
        if is_compressed:
            # Ищем маркер конца JPEG (FF D9) в конце файла
            has_eoi = file_bytes.endswith(b"\xff\xd9") or b"\xff\xd9" in file_bytes[-20:]
            if not has_eoi:
                file_bytes.extend(b"\xff\xd9")
                
            # Добавим Sequence Delimiter (FE FF DD E0 00 00 00 00), если его нет в конце
            has_delim = b"\xfe\xff\xdd\xe0" in file_bytes[-20:]
            if not has_delim:
                file_bytes.extend(b"\xfe\xff\xdd\xe0\x00\x00\x00\x00")
        else:
            # Несжатые пиксели - дополняем нулями до ожидаемого размера
            rows = getattr(ds_meta, "Rows", 512)
            cols = getattr(ds_meta, "Columns", 512)
            bits = getattr(ds_meta, "BitsAllocated", 16)
            expected_pixels = rows * cols * (bits // 8)
            if len(file_bytes) < expected_pixels:
                file_bytes.extend(b"\x00" * (expected_pixels * 2))
                
        # Читаем из BytesIO
        bio = io.BytesIO(file_bytes)
        ds = pydicom.dcmread(bio)
        
        # Чтобы убедиться, что при обращении к pixel_array не упадет, пробуем прочесть его.
        # Если упадет (например, JPEG данные повреждены внутри), подкладываем черный кадр.
        try:
            _ = ds.pixel_array
        except Exception:
            rows = getattr(ds, "Rows", 512)
            cols = getattr(ds, "Columns", 512)
            bits = getattr(ds, "BitsAllocated", 16)
            pixel_repr = getattr(ds, "PixelRepresentation", 0)
            if bits == 16:
                dtype = np.int16 if pixel_repr == 1 else np.uint16
            else:
                dtype = np.int8 if pixel_repr == 1 else np.uint8
            arr = np.zeros((rows, cols), dtype=dtype)
            
            # Динамически переопределяем класс для этого конкретного экземпляра
            class TruncatedDataset(type(ds)):
                @property
                def pixel_array(self):
                    return getattr(self, "_pixel_array", None)
            
            ds._pixel_array = arr
            ds.__class__ = TruncatedDataset
            
        return ds

    def set_current_slice(self, index: int) -> None:
        if index < 0 or index >= len(self.sorted_files):
            return

        self.current_index = index
        self.slider.setValue(index)

        filepath = self.sorted_files[index]
        import pydicom
        try:
            # Читаем файл. Сначала пробуем обычное чтение.
            try:
                ds = pydicom.dcmread(filepath)
                if not hasattr(ds, "pixel_array") or len(ds) == 0:
                    raise ValueError("Empty dataset or missing pixel array")
            except Exception:
                # Если обычное чтение упало, пробуем восстановить частично поврежденный файл
                ds = self.read_truncated_dicom(filepath)

            # Извлекаем параметры окна по умолчанию при первой загрузке серии
            if self.current_index == 0:
                self.default_wc = 40.0
                self.default_ww = 400.0
                wc = getattr(ds, "WindowCenter", None)
                ww = getattr(ds, "WindowWidth", None)
                if wc is not None and ww is not None:
                    try:
                        c_val = wc[0] if hasattr(wc, "__iter__") else wc
                        w_val = ww[0] if hasattr(ww, "__iter__") else ww
                        self.default_wc = float(c_val)
                        self.default_ww = float(w_val)
                    except Exception:
                        pass
                
                # При первом запуске серии используем DICOM пресет
                preset_data = self.cb_presets.currentData()
                if preset_data == "dicom":
                    self.window_center = self.default_wc
                    self.window_width = self.default_ww

            pat_name = getattr(ds, "PatientName", "Unknown")
            pat_id = getattr(ds, "PatientID", "Unknown")
            study_desc = getattr(ds, "StudyDescription", "")
            series_desc = getattr(ds, "SeriesDescription", "")
            
            info_text = f"{pat_name} [{pat_id}] | {study_desc} | {series_desc}"
            self.lbl_info.setText(info_text)
            self.viewer.set_slice_info(index + 1, len(self.sorted_files))

            pixmap = self.dicom_to_pixmap(ds, self.window_width, self.window_center)
            if pixmap:
                self.viewer.set_dicom_image(pixmap, ds)
                self.viewer.set_window_params(self.window_width, self.window_center)
            else:
                raise ValueError("Failed to decode pixel array to pixmap")
                
        except Exception as e:
            # Автоматическая защита от битых файлов: выбрасываем его из списка и пробуем открыть тот же индекс
            print(f"[Viewer] Skipping corrupted file {filepath}: {str(e)}")
            self.sorted_files.pop(index)
            if not self.sorted_files:
                self.lbl_info.setText("Нет доступных изображений в серии.")
                self.viewer.set_slice_info(0, 0)
                self.viewer.clear_viewer()
                return

            self.slider.setRange(0, len(self.sorted_files) - 1)
            new_index = min(index, len(self.sorted_files) - 1)
            self.set_current_slice(new_index)

    def on_slider_changed(self, value: int) -> None:
        if not self.is_loading and value != self.current_index:
            self.set_current_slice(value)

    def on_slice_scrolled(self, step: int) -> None:
        new_index = self.current_index + step
        if 0 <= new_index < len(self.sorted_files):
            self.set_current_slice(new_index)

    def on_window_changed(self, width: float, center: float) -> None:
        self.window_width = width
        self.window_center = center
        
        # Если изменение пришло от мыши на изображении, сбрасываем выбранный пресет
        if self.sender() == self.viewer:
            self.cb_presets.blockSignals(True)
            self.cb_presets.setCurrentIndex(-1)
            self.cb_presets.blockSignals(False)
            
        if hasattr(self, "hu_panel") and hasattr(self, "hu_slider"):
            lower = center - width / 2.0
            upper = center + width / 2.0
            
            self.hu_slider.blockSignals(True)
            self.hu_slider.set_values(lower, upper)
            self.hu_slider.blockSignals(False)
            
            self.lbl_upper_hu.setText(f"{int(upper)} HU")
            self.lbl_lower_hu.setText(f"{int(lower)} HU")
            
        self.update_current_slice_pixels()

    def update_current_slice_pixels(self) -> None:
        ds = self.viewer.current_dataset
        if ds is not None:
            pixmap = self.dicom_to_pixmap(ds, self.window_width, self.window_center)
            if pixmap:
                self.viewer.set_dicom_image(pixmap, ds)
                self.viewer.set_window_params(self.window_width, self.window_center)
            return

        if self.current_index < 0 or self.current_index >= len(self.sorted_files):
            return
        filepath = self.sorted_files[self.current_index]
        import pydicom
        try:
            ds = pydicom.dcmread(filepath)
            pixmap = self.dicom_to_pixmap(ds, self.window_width, self.window_center)
            if pixmap:
                self.viewer.set_dicom_image(pixmap, ds)
                self.viewer.set_window_params(self.window_width, self.window_center)
        except Exception:
            pass

    def apply_preset(self, index: int) -> None:
        preset_type = self.cb_presets.itemData(index)
        
        if preset_type == "dicom":
            self.window_width = self.default_ww
            self.window_center = self.default_wc
        elif preset_type == "soft":
            self.window_width = 400.0
            self.window_center = 40.0
        elif preset_type == "bone":
            self.window_width = 1500.0
            self.window_center = 300.0
        elif preset_type == "lung":
            self.window_width = 1500.0
            self.window_center = -600.0
        elif preset_type == "brain":
            self.window_width = 80.0
            self.window_center = 40.0

        self.on_window_changed(self.window_width, self.window_center)

    def dicom_to_pixmap(self, ds, window_width: float, window_center: float) -> QPixmap | None:
        try:
            import numpy as np
            if not hasattr(ds, "pixel_array"):
                return None

            original_ts = getattr(ds.file_meta, "TransferSyntaxUID", None)
            if original_ts and not hasattr(ds, "original_transfer_syntax"):
                ds.original_transfer_syntax = original_ts

            try:
                ds.decompress()
            except Exception:
                pass

            arr = ds.pixel_array.astype(float)
            slope = float(getattr(ds, "RescaleSlope", 1.0))
            intercept = float(getattr(ds, "RescaleIntercept", 0.0))
            arr = arr * slope + intercept

            min_val = window_center - window_width / 2.0
            max_val = window_center + window_width / 2.0

            arr = np.clip(arr, min_val, max_val)
            arr = ((arr - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)

            height, width = arr.shape
            bytes_per_line = width

            self._temp_arr = np.ascontiguousarray(arr)
            qimg = QImage(self._temp_arr.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)
            return QPixmap.fromImage(qimg)
        except Exception:
            return None


class CustomSplitterHandle(QSplitterHandle):
    """Кастомная ручка сплиттера со стрелочкой-рисованием (шевроном) и блокировкой Drag."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.is_collapsed = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Программно фиксируем ширину/высоту ручки сплиттера
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedWidth(8)
        else:
            self.setFixedHeight(8)

    def get_handle_index(self) -> int:
        splitter = self.splitter()
        if not splitter:
            return -1
        for i in range(1, splitter.count()):
            if splitter.handle(i) is self:
                return i
        return -1

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        idx = self.get_handle_index()
        splitter = self.splitter()
        if splitter and idx != -1:
            sizes = splitter.sizes()
            if splitter.orientation() == Qt.Orientation.Horizontal:
                if len(sizes) >= 2 and idx == 1:
                    self.is_collapsed = (sizes[0] <= 5)
            else:
                if len(sizes) >= 3:
                    if idx == 1:
                        self.is_collapsed = (sizes[0] <= 5)
                    elif idx == 2:
                        self.is_collapsed = (sizes[1] <= 5)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        # Запрещаем изменение размеров перетаскиванием мыши вручную
        event.ignore()

    def mousePressEvent(self, event) -> None:
        # При клике левой кнопкой мыши сворачиваем/разворачиваем панель
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.get_handle_index()
            if idx != -1:
                self.toggle_collapse()
        else:
            event.ignore()

    def paintEvent(self, event) -> None:
        idx = self.get_handle_index()
        if idx == -1:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Цвета по умолчанию
        line_color = QColor("#3F3F46")
        if self.underMouse():
            arrow_color = QColor("#3B82F6")
        else:
            arrow_color = QColor("#71717A")

        # Загружаем палитру
        main_win = self.window()
        if hasattr(main_win, "current_theme") and hasattr(main_win, "THEMES"):
            palette = main_win.THEMES[main_win.current_theme]
            line_color = QColor(palette.get("BORDER_COLOR", "#3F3F46"))
            if self.underMouse():
                arrow_color = QColor(palette.get("ACCENT_COLOR", "#3B82F6"))
            else:
                arrow_color = QColor(palette.get("TEXT_MUTED", "#71717A"))

        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2

        # Рисуем разделительную линию и стрелочку в зависимости от ориентации
        from PyQt6.QtGui import QPolygon
        from PyQt6.QtCore import QPoint
        poly = QPolygon()

        if self.orientation() == Qt.Orientation.Horizontal:
            # Вертикальная ручка горизонтального сплиттера (для левого дерева)
            painter.setPen(QPen(line_color, 1))
            painter.drawLine(cx, 0, cx, h)

            # Рисуем плоскую высокую стрелочку: ширина 5px, высота 20px (основание вдвое шире)
            if not self.is_collapsed:
                # Стрелочка влево ◀
                poly.append(QPoint(cx - 2, cy))
                poly.append(QPoint(cx + 2, cy - 10))
                poly.append(QPoint(cx + 2, cy + 10))
            else:
                # Стрелочка вправо ▶
                poly.append(QPoint(cx + 2, cy))
                poly.append(QPoint(cx - 2, cy - 10))
                poly.append(QPoint(cx - 2, cy + 10))
        else:
            # Горизонтальная ручка вертикального сплиттера (для папок/настроек)
            painter.setPen(QPen(line_color, 1))
            # Делаем линию немного короче, чтобы она не наползала на скругленные углы плашек
            painter.drawLine(15, cy, w - 15, cy)

            # Рисуем плоскую широкую стрелочку: ширина 20px (основание вдвое шире), высота 5px
            if not self.is_collapsed:
                # Стрелочка вверх ▲
                poly.append(QPoint(cx, cy - 2))
                poly.append(QPoint(cx - 10, cy + 2))
                poly.append(QPoint(cx + 10, cy + 2))
            else:
                # Стрелочка вниз ▼
                poly.append(QPoint(cx, cy + 2))
                poly.append(QPoint(cx - 10, cy - 2))
                poly.append(QPoint(cx + 10, cy - 2))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(arrow_color))
        painter.drawPolygon(poly)

    def toggle_collapse(self) -> None:
        splitter = self.splitter()
        if not splitter:
            return

        sizes = splitter.sizes()
        idx = self.get_handle_index()

        if splitter.orientation() == Qt.Orientation.Horizontal:
            # Горизонтальный сплиттер (левое дерево, индекс ручки 1)
            if len(sizes) < 2:
                return
            if idx == 1:
                if not self.is_collapsed:
                    new_sizes = [0, sizes[1] + sizes[0]]
                    splitter.setSizes(new_sizes)
                    self.is_collapsed = True
                else:
                    new_sizes = [385, max(50, sizes[1] + sizes[0] - 385)]
                    splitter.setSizes(new_sizes)
                    self.is_collapsed = False
        else:
            # Вертикальный сплиттер (папки/настройки)
            if len(sizes) < 3:
                return
            if idx == 1:
                # Сворачиваем/разворачиваем первую панель (folder_frame, индекс 0)
                if not self.is_collapsed:
                    new_sizes = [0, sizes[1], sizes[2] + sizes[0]]
                    splitter.setSizes(new_sizes)
                    self.is_collapsed = True
                else:
                    new_sizes = [90, sizes[1], max(50, sizes[2] + sizes[0] - 90)]
                    splitter.setSizes(new_sizes)
                    self.is_collapsed = False
            elif idx == 2:
                # Сворачиваем/разворачиваем вторую панель (settings_frame, индекс 1)
                if not self.is_collapsed:
                    new_sizes = [sizes[0], 0, sizes[2] + sizes[1]]
                    splitter.setSizes(new_sizes)
                    self.is_collapsed = True
                else:
                    new_sizes = [sizes[0], 135, max(50, sizes[2] + sizes[1] - 135)]
                    splitter.setSizes(new_sizes)
                    self.is_collapsed = False

        self.update()


class CustomSplitter(QSplitter):
    """Кастомный сплиттер (горизонтальный или вертикальный) с фиксированными размерами секций и отключенным Drag."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget = None) -> None:
        super().__init__(orientation, parent)

    def createHandle(self) -> QSplitterHandle:
        return CustomSplitterHandle(self.orientation(), self)
