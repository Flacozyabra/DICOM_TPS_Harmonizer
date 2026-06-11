import sys
from pathlib import Path
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QGuiApplication, QPixmap, QPainter, QPen, QColor, QPainterPath, QBrush

def main():
    # Создаем минимальное GUI-приложение для инициализации QPixmap/QPainter
    app = QGuiApplication(sys.argv)
    
    project_root = Path(__file__).resolve().parents[1]
    themes_dir = project_root / "themes"
    themes_dir.mkdir(exist_ok=True)
    
    # 1. arrow_right.png (Белая стрелка вправо, 16x16)
    pixmap_right = QPixmap(16, 16)
    pixmap_right.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_right)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(2.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    
    # Полилиния стрелки вправо
    points_right = [
        QPointF(5.5, 3.5),
        QPointF(10.5, 8.0),
        QPointF(5.5, 12.5)
    ]
    painter.drawPolyline(points_right)
    painter.end()
    
    pixmap_right.save(str(themes_dir / "arrow_right.png"), "PNG")
    print("Generated arrow_right.png")
    
    # 2. arrow_down.png (Синяя стрелка вниз, 16x16)
    pixmap_down = QPixmap(16, 16)
    pixmap_down.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_down)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    pen_blue = QPen(QColor("#3B82F6"))
    pen_blue.setWidthF(2.5)
    pen_blue.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen_blue.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen_blue)
    
    # Полилиния стрелки вниз
    points_down = [
        QPointF(3.5, 5.5),
        QPointF(8.0, 10.5),
        QPointF(12.5, 5.5)
    ]
    painter.drawPolyline(points_down)
    painter.end()
    
    pixmap_down.save(str(themes_dir / "arrow_down.png"), "PNG")
    print("Generated arrow_down.png")
    
    # 3. checkbox_checked.png (Белая галочка, 16x16)
    pixmap_checkbox = QPixmap(16, 16)
    pixmap_checkbox.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_checkbox)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    pen_check = QPen(QColor("#FFFFFF"))
    pen_check.setWidthF(2.5)
    pen_check.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen_check.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen_check)
    
    # Галочка
    points_check = [
        QPointF(3.0, 7.5),
        QPointF(6.5, 11.0),
        QPointF(12.5, 4.5)
    ]
    painter.drawPolyline(points_check)
    painter.end()
    
    pixmap_checkbox.save(str(themes_dir / "checkbox_checked.png"), "PNG")
    print("Generated checkbox_checked.png")
    
    # 4. splitter_dots_v.png (Вертикальные точки для горизонтального сплиттера, 3x16)
    pixmap_dots_v = QPixmap(3, 16)
    pixmap_dots_v.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_dots_v)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#9CA3AF"))
    
    # 3 точки вертикально
    painter.drawEllipse(QPointF(1.5, 4.0), 0.8, 0.8)
    painter.drawEllipse(QPointF(1.5, 8.0), 0.8, 0.8)
    painter.drawEllipse(QPointF(1.5, 12.0), 0.8, 0.8)
    painter.end()
    
    pixmap_dots_v.save(str(themes_dir / "splitter_dots_v.png"), "PNG")
    print("Generated splitter_dots_v.png")
    
    # 5. splitter_dots_h.png (Горизонтальные точки для вертикального сплиттера, 16x3)
    pixmap_dots_h = QPixmap(16, 3)
    pixmap_dots_h.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_dots_h)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#9CA3AF"))
    
    # 3 точки горизонтально
    painter.drawEllipse(QPointF(4.0, 1.5), 0.8, 0.8)
    painter.drawEllipse(QPointF(8.0, 1.5), 0.8, 0.8)
    painter.drawEllipse(QPointF(12.0, 1.5), 0.8, 0.8)
    painter.end()
    
    pixmap_dots_h.save(str(themes_dir / "splitter_dots_h.png"), "PNG")
    print("Generated splitter_dots_h.png")
    
    # 6. ruler.png (Монохромная линейка, 24x24, #D1D5DB)
    pixmap_ruler = QPixmap(24, 24)
    pixmap_ruler.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_ruler)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    pen_ruler = QPen(QColor("#D1D5DB"))
    pen_ruler.setWidthF(1.5)
    pen_ruler.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen_ruler.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen_ruler)
    
    # Главная линия
    painter.drawLine(QPointF(4.5, 19.5), QPointF(19.5, 4.5))
    # Засечки по краям
    painter.drawLine(QPointF(2.5, 17.5), QPointF(6.5, 21.5))
    painter.drawLine(QPointF(17.5, 2.5), QPointF(21.5, 6.5))
    # Деления
    painter.drawLine(QPointF(7.5, 16.5), QPointF(9.5, 18.5))
    painter.drawLine(QPointF(11.5, 12.5), QPointF(13.5, 14.5))
    painter.drawLine(QPointF(15.5, 8.5), QPointF(17.5, 10.5))
    painter.end()
    
    pixmap_ruler.save(str(themes_dir / "ruler.png"), "PNG")
    print("Generated ruler.png")
    
    # 7. hu.png (Монохромный контраст, 24x24, #D1D5DB)
    pixmap_hu = QPixmap(24, 24)
    pixmap_hu.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_hu)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    pen_hu = QPen(QColor("#D1D5DB"))
    pen_hu.setWidthF(1.5)
    painter.setPen(pen_hu)
    
    # Заливка правой части
    painter.setBrush(QBrush(QColor("#D1D5DB")))
    painter.drawChord(4, 4, 16, 16, -90 * 16, 180 * 16)
    # Контур левой части (рисуем весь круг без заливки)
    painter.setBrush(QBrush(Qt.GlobalColor.transparent))
    painter.drawEllipse(4, 4, 16, 16)
    painter.end()
    
    pixmap_hu.save(str(themes_dir / "hu.png"), "PNG")
    print("Generated hu.png")
    
    # 8. eye.png (Монохромный глаз, 24x24, #D1D5DB)
    pixmap_eye = QPixmap(24, 24)
    pixmap_eye.fill(Qt.GlobalColor.transparent)
    
    painter = QPainter(pixmap_eye)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    pen_eye = QPen(QColor("#D1D5DB"))
    pen_eye.setWidthF(1.5)
    painter.setPen(pen_eye)
    
    # Контур глаза
    path = QPainterPath()
    path.moveTo(3.0, 12.0)
    path.quadTo(12.0, 4.5, 21.0, 12.0)
    path.quadTo(12.0, 19.5, 3.0, 12.0)
    painter.drawPath(path)
    
    # Зрачок
    painter.setBrush(QBrush(QColor("#D1D5DB")))
    painter.drawEllipse(QPointF(12.0, 12.0), 3.2, 3.2)
    painter.end()
    
    pixmap_eye.save(str(themes_dir / "eye.png"), "PNG")
    print("Generated eye.png")



if __name__ == "__main__":
    main()
