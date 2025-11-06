
"""
Interactive QLabel pour le dessin de ROI polygones sur images (B-mode si dispo)
"""
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QPainter, QPen, QPixmap, QColor, QPolygon
from typing import Optional, List

class InteractiveImageLabel(QLabel):
    roi_drawn = pyqtSignal(list)  # Liste de points (polygone) en coordonnées image

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAlignment(Qt.AlignCenter)
        self.drawing_enabled = False
        self.drawing_active = False
        self.current_polygon: List[QPoint] = []
        self.polygons: List[List[QPoint]] = []
        self.selected_polygon_index: Optional[int] = None
        self._bmode_pixmap: Optional[QPixmap] = None
        self._main_pixmap: Optional[QPixmap] = None
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.offset_x = 0
        self.offset_y = 0

    def set_drawing_enabled(self, enabled: bool):
        self.drawing_enabled = enabled
        if enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
            self.drawing_active = False
            self.current_polygon = []
        self.update()

    def set_polygons(self, polygons: List[List[QPoint]]):
        self.polygons = polygons
        self.update()

    def set_images(self, main_pixmap: QPixmap, bmode_pixmap: Optional[QPixmap] = None):
        self._main_pixmap = main_pixmap
        if bmode_pixmap is not None:
            self._bmode_pixmap = bmode_pixmap
        self.update()

    def widget_to_image_coords(self, point: QPoint) -> tuple:
        x = int((point.x() - self.offset_x) * self.scale_x)
        y = int((point.y() - self.offset_y) * self.scale_y)
        return (x, y)

    def image_to_widget_coords(self, x: int, y: int) -> QPoint:
        wx = int(x / self.scale_x + self.offset_x)
        wy = int(y / self.scale_y + self.offset_y)
        return QPoint(wx, wy)

    def mousePressEvent(self, event):
        if self.drawing_enabled:
            if event.button() == Qt.LeftButton:
                self.drawing_active = True
                # Conversion coordonnées widget -> image
                pixmap = self._bmode_pixmap if self._bmode_pixmap is not None else self._main_pixmap
                if pixmap is not None:
                    pixmap_rect = pixmap.rect()
                    widget_rect = self.rect()
                    scale_x = pixmap_rect.width() / widget_rect.width()
                    scale_y = pixmap_rect.height() / widget_rect.height()
                    pt_widget = event.pos()
                    pt_img = QPoint(int(pt_widget.x() * scale_x), int(pt_widget.y() * scale_y))
                    self.current_polygon.append(pt_img)
                    print(f"Ajout point (img): {pt_img}")
                    self.update()
            elif event.button() == Qt.RightButton and self.drawing_active:
                self.finish_polygon()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.drawing_enabled and self.drawing_active:
            self.finish_polygon()
        super().mouseDoubleClickEvent(event)

    def finish_polygon(self):
        self.drawing_active = False
        if len(self.current_polygon) > 2:
            self.polygons.append(self.current_polygon.copy())
            poly_img = [self.widget_to_image_coords(pt) for pt in self.current_polygon]
            self.roi_drawn.emit(poly_img)
        self.current_polygon = []
        self.update()

    def mouseMoveEvent(self, event):
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        pixmap = self._bmode_pixmap if self._bmode_pixmap is not None else self._main_pixmap
        if pixmap is not None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            pixmap_rect = pixmap.rect()
            widget_rect = self.rect()
            scale_x = widget_rect.width() / pixmap_rect.width()
            scale_y = widget_rect.height() / pixmap_rect.height()
            painter.drawPixmap(widget_rect, pixmap)
            def transform_point(pt):
                return QPoint(int(pt.x() * scale_x), int(pt.y() * scale_y))
            # Polygones existants
            pen = QPen(QColor(255, 0, 0), 2)
            painter.setPen(pen)
            for poly in self.polygons:
                if len(poly) > 2:
                    poly_trans = [transform_point(pt) for pt in poly]
                    painter.drawPolygon(QPolygon(poly_trans))
                    for pt in poly_trans:
                        painter.setPen(QPen(QColor(255,0,0), 2))
                        painter.setBrush(QColor(255,0,0))
                        painter.drawEllipse(pt, 4, 4)
            # Polygone en cours
            if self.drawing_active and len(self.current_polygon) > 0:
                pen = QPen(QColor(255, 255, 0), 2, Qt.DashLine)
                painter.setPen(pen)
                if len(self.current_polygon) > 1:
                    poly_trans = [transform_point(pt) for pt in self.current_polygon]
                    painter.drawPolyline(QPolygon(poly_trans))
                for pt in self.current_polygon:
                    pt_trans = transform_point(pt)
                    painter.setPen(QPen(QColor(255,255,0), 2))
                    painter.setBrush(QColor(255,255,0))
                    painter.drawEllipse(pt_trans, 4, 4)
            painter.end()

    def remove_selected_polygon(self):
        if self.selected_polygon_index is not None and 0 <= self.selected_polygon_index < len(self.polygons):
            del self.polygons[self.selected_polygon_index]
            self.selected_polygon_index = None
            self.update()

    def clear_polygons(self):
        self.polygons = []
        self.selected_polygon_index = None
        self.update()
