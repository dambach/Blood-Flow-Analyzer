"""
TIC plot widget with PyQtGraph
Interactive Time-Intensity Curve plot with frame synchronization
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QApplication
from PyQt5.QtCore import Qt, pyqtSignal
import pyqtgraph as pg
import numpy as np


class TICPlotWidget(QWidget):
    """Interactive TIC plot avec crosshair et clics sur points"""
    
    # Signal unique: clic sur un point (roi_label, idx)
    point_clicked = pyqtSignal(str, int)   # (roi_label, idx)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Mappe label -> dict(t, y, valid_mask, line, scatter, color)
        self.tic_curves = {}
        self.crosshair_line = None
        self._last_clicked_idx_by_label = {}
        # Courbes de fit (overlays): key=(roi_label, model) -> PlotDataItem
        self.fit_curves = {}
        # Sélecteur d'intervalle (LinearRegionItem), masqué par défaut
        self._region = None

        self._create_widgets()
        self._create_layout()
    
    def _create_widgets(self):
        """Create widgets"""
        # Custom ViewBox: désactiver le pan au drag gauche (clic gauche réservé à la sélection de points)
        class _LeftClickSelectViewBox(pg.ViewBox):
            def mouseDragEvent(self, event):
                try:
                    if event.button() == Qt.LeftButton:
                        event.ignore()
                        return
                except Exception:
                    pass
                super().mouseDragEvent(event)

        vb = _LeftClickSelectViewBox()
        # PyQtGraph PlotWidget avec ViewBox custom
        self.plot_widget = pg.PlotWidget(viewBox=vb)
        # Alias de compatibilité (utilisé par napari_main_window.py)
        try:
            self.plotItem = self.plot_widget.getPlotItem()
        except Exception:
            self.plotItem = self.plot_widget.plotItem if hasattr(self.plot_widget, 'plotItem') else None
        self.plot_widget.setLabel('left', 'ΔVI (AU)')
        self.plot_widget.setLabel('bottom', 'Time (s)')
        self.plot_widget.setTitle('Time-Intensity Curves')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        # Laisser la souris active sur le ViewBox (pas de désactivation du pan/zoom ici)
        try:
            self.plot_widget.setMenuEnabled(False)
        except Exception:
            pass
        # Click n'importe où dans le plot pour naviguer (sans devoir cliquer un point)
        try:
            self.plot_widget.scene().sigMouseClicked.connect(self._on_scene_clicked)
        except Exception:
            pass
        # Capture clic souris (pour connaître bouton/modifieurs)
        try:
            self.plot_widget.scene().sigMouseClicked.connect(self._on_scene_mouse_clicked)
        except Exception:
            pass
        
        # Crosshair (vertical line)
        self.crosshair_line = pg.InfiniteLine(
            angle=90, 
            movable=False,
            pen=pg.mkPen(color='r', width=2, style=Qt.DashLine)
        )
        self.plot_widget.addItem(self.crosshair_line)
        self.crosshair_line.setVisible(False)
        
        # Sélecteur d'intervalle pour le fit (caché par défaut)
        try:
            self._region = pg.LinearRegionItem(values=None, orientation=None, movable=True)
            self._region.setZValue(800)
            self._region.setVisible(False)
            # Style léger
            self._region.setBrush(pg.mkBrush(100, 100, 255, 40))
            self._region.setPen(pg.mkPen(100, 100, 255, 120, style=Qt.DashLine))
            self.plot_widget.addItem(self._region)
        except Exception:
            self._region = None
    
    def _create_layout(self):
        """Create layout"""
        layout = QVBoxLayout()
        layout.addWidget(self.plot_widget)
        self.setLayout(layout)
    
    def add_tic_curve(self, roi_label: str, time: np.ndarray, dvi: np.ndarray, valid_mask: np.ndarray, color=None):
        """Ajoute une courbe TIC: ligne + points, avec masque de validité.

        Args:
            roi_label: label ROI
            time: np.ndarray (T,)
            dvi: np.ndarray (T,)
            valid_mask: np.ndarray (T,) bool
            color: couleur principale
        """
        if color is None:
            colors = ['r', 'g', 'b', 'c', 'm', 'y', 'w']
            color = colors[len(self.tic_curves) % len(colors)]

        # Ligne continue
        line_item = self.plot_widget.plot(
            time,
            dvi,
            pen=pg.mkPen(color=color, width=2),
            name=roi_label,
        )
        try:
            line_item.setZValue(500)
        except Exception:
            pass

        # Scatter avec style par-point selon valid_mask
        spots = []
        col_pen = pg.mkPen(color=color)
        col_brush = pg.mkBrush(color)
        gray_pen = pg.mkPen(color=(160, 160, 160, 160))
        gray_brush = pg.mkBrush(160, 160, 160, 140)
        for i in range(len(time)):
            if valid_mask[i]:
                pen = col_pen
                brush = col_brush
            else:
                pen = gray_pen
                brush = gray_brush
            spots.append({
                'pos': (float(time[i]), float(dvi[i])),
                'data': int(i),
                'pen': pen,
                'brush': brush,
                'size': 6,
                'symbol': 'o',
            })
        scatter_item = pg.ScatterPlotItem()
        scatter_item.addPoints(spots)
        self.plot_widget.addItem(scatter_item)
        try:
            scatter_item.setZValue(1000)
        except Exception:
            pass
        try:
            scatter_item.sigClicked.connect(self._make_scatter_handler(roi_label))
        except Exception:
            pass

        self.tic_curves[roi_label] = {
            't': time,
            'y': dvi,
            'valid_mask': valid_mask,
            'line': line_item,
            'scatter': scatter_item,
            'color': color,
        }
    
    def remove_tic_curve(self, roi_label: str):
        """Remove TIC curve"""
        if roi_label in self.tic_curves:
            info = self.tic_curves.pop(roi_label)
            try:
                self.plot_widget.removeItem(info['line'])
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(info['scatter'])
            except Exception:
                pass

    def rename_tic_curve(self, old_label: str, new_label: str):
        """Rename an existing TIC curve label in legend without replotting."""
        if old_label in self.tic_curves and new_label not in self.tic_curves:
            info = self.tic_curves.pop(old_label)
            try:
                info['line'].setName(new_label)
            except Exception:
                pass
            self.tic_curves[new_label] = info

    def update_tic_curve(self, roi_label: str, time: np.ndarray, dvi: np.ndarray, valid_mask: np.ndarray):
        """Met à jour données et style d'une courbe TIC existante."""
        info = self.tic_curves.get(roi_label)
        if not info:
            return
        info['t'] = time
        info['y'] = dvi
        info['valid_mask'] = valid_mask
        # MAJ ligne
        try:
            info['line'].setData(time, dvi)
        except Exception:
            pass
        # MAJ scatter per-point
        try:
            self.plot_widget.removeItem(info['scatter'])
        except Exception:
            pass
        color = info.get('color', 'w')
        col_pen = pg.mkPen(color=color)
        col_brush = pg.mkBrush(color)
        gray_pen = pg.mkPen(color=(160, 160, 160, 160))
        gray_brush = pg.mkBrush(160, 160, 160, 140)
        spots = []
        for i in range(len(time)):
            if valid_mask[i]:
                pen = col_pen
                brush = col_brush
            else:
                pen = gray_pen
                brush = gray_brush
            spots.append({
                'pos': (float(time[i]), float(dvi[i])),
                'data': int(i),
                'pen': pen,
                'brush': brush,
                'size': 6,
                'symbol': 'o',
            })
        scatter_item = pg.ScatterPlotItem()
        scatter_item.addPoints(spots)
        self.plot_widget.addItem(scatter_item)
        try:
            scatter_item.setZValue(1000)
        except Exception:
            pass
        try:
            scatter_item.sigClicked.connect(self._make_scatter_handler(roi_label))
        except Exception:
            pass
        info['scatter'] = scatter_item
    
    def update_crosshair(self, frame_idx: int):
        """Update crosshair position based on frame index"""
        if not self.tic_curves:
            return
        
        # Get time from first curve
        first_curve = list(self.tic_curves.values())[0]
        time = first_curve['t']
        
        if frame_idx < len(time):
            time_pos = time[frame_idx]
            self.crosshair_line.setPos(time_pos)
            self.crosshair_line.setVisible(True)
    
    def clear(self):
        """Clear all curves"""
        for roi_label in list(self.tic_curves.keys()):
            self.remove_tic_curve(roi_label)
        # Nettoyer les courbes de fit
        self.clear_fit_curves()

    # --- internal handlers ---
    def _on_scatter_clicked(self, roi_label: str, _plt, points):
        if not points:
            return
        pt = points[0]
        try:
            idx = int(pt.data()) if pt.data() is not None else None
        except Exception:
            idx = None
        if idx is None:
            return
        # Émettre uniquement le clic pour navigation
        self.point_clicked.emit(roi_label, idx)

    def _make_scatter_handler(self, roi_label: str):
        def handler(scatter, points):
            self._on_scatter_clicked(roi_label, scatter, points)
        return handler

    def _on_scene_clicked(self, evt):
        """Gère le clic gauche n'importe où dans le plot pour naviguer vers la frame la plus proche.
        N'émet pas de label de ROI spécifique (utilise '__plot__' en sentinelle) pour éviter de
        modifier la cible '_last_tic_target' côté fenêtre principale.
        """
        try:
            if evt.button() != Qt.LeftButton:
                return
        except Exception:
            return
        if not self.tic_curves:
            return
        # Convertir la position de la scène en coordonnées du graphique
        try:
            pos = evt.scenePos()
            vb = self.plot_widget.getPlotItem().getViewBox()
            mouse_pt = vb.mapSceneToView(pos)
            x = float(mouse_pt.x())
        except Exception:
            return
        # Trouver l'index le plus proche sur l'axe du temps de la première courbe
        try:
            first_curve = list(self.tic_curves.values())[0]
            t = first_curve.get('t')
            if t is None or len(t) == 0:
                return
            idx = int(np.argmin(np.abs(t - x)))
        except Exception:
            return
        # Emettre un signal de navigation uniquement
        try:
            self.point_clicked.emit('__plot__', idx)
        except Exception:
            pass

    # ==========================
    # API Fit overlays & Region
    # ==========================
    def set_fit_curve(self, roi_label: str, model: str, t: np.ndarray, y: np.ndarray, color: str = '#000', width: float = 2.0, dashed: bool = True):
        """Ajoute/MàJ une courbe de fit pour une ROI et un modèle."""
        key = (roi_label, model)
        try:
            pen = pg.mkPen(color=color, width=width, style=Qt.DashLine if dashed else Qt.SolidLine)
        except Exception:
            pen = None
        line = self.fit_curves.get(key)
        if line is None:
            try:
                line = self.plot_widget.plot(t, y, pen=pen, name=f"{roi_label} · {model}")
                self.fit_curves[key] = line
            except Exception:
                return
        else:
            try:
                line.setData(t, y)
                if pen is not None:
                    line.setPen(pen)
            except Exception:
                pass

    def clear_fit_curves(self, roi_label: str = None):
        """Supprime toutes les courbes de fit (ou celles d'une ROI)."""
        if roi_label is None:
            keys = list(self.fit_curves.keys())
        else:
            keys = [k for k in list(self.fit_curves.keys()) if k[0] == roi_label]
        for k in keys:
            item = self.fit_curves.get(k)
            if item is None:
                continue
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
            self.fit_curves.pop(k, None)

    def enable_region_selector(self, enable: bool, default_span_s: float = 5.0):
        """Affiche/masque le sélecteur d'intervalle. Initialise une plage par défaut si nécessaire."""
        if self._region is None:
            return
        self._region.setVisible(bool(enable))
        if not enable:
            return
        # Init si pas encore défini
        try:
            region = self._region.getRegion()
        except Exception:
            region = None
        if not region or any([r is None for r in region]):
            if not self.tic_curves:
                return
            first = list(self.tic_curves.values())[0]
            t = np.asarray(first.get('t', []), dtype=float)
            if t.size == 0:
                return
            tmin, tmax = float(np.min(t)), float(np.max(t))
            # Centrage sur le crosshair si visible
            try:
                if self.crosshair_line is not None and self.crosshair_line.isVisible():
                    cx = float(self.crosshair_line.value()) if hasattr(self.crosshair_line, 'value') else float(self.crosshair_line.pos().x())
                else:
                    cx = (tmin + tmax) * 0.5
            except Exception:
                cx = (tmin + tmax) * 0.5
            half = max(0.1, default_span_s * 0.5)
            a = max(tmin, cx - half)
            b = min(tmax, cx + half)
            if b <= a:
                a, b = tmin, min(tmin + default_span_s, tmax)
            try:
                self._region.setRegion((a, b))
            except Exception:
                pass

    def set_region_range(self, t0: float, t1: float):
        if self._region is None:
            return
        try:
            a, b = float(min(t0, t1)), float(max(t0, t1))
            self._region.setRegion((a, b))
        except Exception:
            pass

    def get_region_range(self):
        if self._region is None or not self._region.isVisible():
            return None
        try:
            a, b = self._region.getRegion()
            if a is None or b is None:
                return None
            a, b = float(a), float(b)
            if np.isfinite(a) and np.isfinite(b) and b > a:
                return a, b
        except Exception:
            return None
        return None
