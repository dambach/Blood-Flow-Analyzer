"""
Napari widget intégré dans PyQt5 pour affichage et ROI interactifs
"""
import os
os.environ['QT_API'] = 'pyqt5'  # Force Napari à utiliser PyQt5

from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import pyqtSignal
import numpy as np
from typing import Optional, List, Tuple


class NapariViewerWidget(QWidget):
    """Widget Napari intégré dans PyQt5"""
    
    # Signals
    roi_added = pyqtSignal(list, str)  # points (polygon), label
    roi_removed = pyqtSignal(str)  # label
    frame_changed = pyqtSignal(int)  # frame index
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Import napari
        import napari
        
        # Créer le viewer Napari (show=False évite qu'il ouvre sa propre QMainWindow)
        self.viewer = napari.Viewer(show=False)

        # _qt_viewer = widget Qt interne (pas le QMainWindow napari)
        # C'est la clé pour l'intégration sur macOS !
        qt_viewer_widget = self.viewer.window._qt_viewer

        # Intégrer dans notre layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(qt_viewer_widget, stretch=1)
        self.setLayout(layout)
        
        # Layers references
        self.bmode_layer = None
        self.ceus_layer = None
        self.shapes_layer = None
        
        # Data references
        self.bmode_stack = None
        self.ceus_stack = None
        
        # Créer le layer de shapes pour les ROI
        self._create_shapes_layer()
        
        # Connecter les signaux
        self._connect_signals()
    
    def _create_shapes_layer(self):
        """Créer le layer de shapes pour les ROI"""
        self.shapes_layer = self.viewer.add_shapes(
            name='ROI',
            shape_type='polygon',
            edge_width=2,
            edge_color='red',
            face_color='transparent',
            opacity=0.7
        )
        
        # Mode d'ajout : permet de dessiner
        self.shapes_layer.mode = 'add_polygon'
    
    def _connect_signals(self):
        """Connecter les signaux Napari aux signaux PyQt"""
        # Détecter l'ajout de ROI
        @self.shapes_layer.events.data.connect
        def on_shapes_changed(event):
            # Récupérer les nouvelles shapes
            if len(self.shapes_layer.data) > len(self.shapes_layer.properties.get('label', [])):
                # Nouvelle shape ajoutée
                new_polygon = self.shapes_layer.data[-1]
                label = f"ROI_{len(self.shapes_layer.data)}"
                self.roi_added.emit(new_polygon.tolist(), label)
        
        # Détecter le changement de frame
        @self.viewer.dims.events.current_step.connect
        def on_frame_changed(event):
            if len(self.viewer.dims.current_step) > 0:
                frame_idx = self.viewer.dims.current_step[0]
                self.frame_changed.emit(frame_idx)
    
    def set_bmode_stack(self, bmode_stack: np.ndarray):
        """Afficher le stack B-mode"""
        self.bmode_stack = bmode_stack
        
        if self.bmode_layer is not None:
            self.viewer.layers.remove(self.bmode_layer)
        
        self.bmode_layer = self.viewer.add_image(
            bmode_stack,
            name='B-mode',
            colormap='gray',
            blending='opaque',
            visible=True
        )
    
    def set_ceus_stack(self, ceus_stack: np.ndarray, colormap='magma', preprocessed=False):
        """Afficher le stack CEUS"""
        self.ceus_stack = ceus_stack
        
        if self.ceus_layer is not None:
            self.viewer.layers.remove(self.ceus_layer)
        
        name = 'CEUS (preprocessed)' if preprocessed else 'CEUS'
        self.ceus_layer = self.viewer.add_image(
            ceus_stack,
            name=name,
            colormap=colormap,
            blending='additive',
            visible=True,
            opacity=0.7
        )
    
    def enable_roi_drawing(self, enabled: bool):
        """Activer/désactiver le mode dessin de ROI"""
        if enabled:
            self.shapes_layer.mode = 'add_polygon'
        else:
            self.shapes_layer.mode = 'pan_zoom'
    
    def add_roi_from_coords(self, polygon: np.ndarray, label: str, color: str = 'red'):
        """Ajouter un ROI depuis des coordonnées"""
        self.shapes_layer.add_polygons([polygon], edge_color=color)
    
    def clear_rois(self):
        """Effacer tous les ROI"""
        self.shapes_layer.data = []
    
    def get_rois(self) -> List[np.ndarray]:
        """Récupérer tous les ROI (polygones)"""
        return [polygon for polygon in self.shapes_layer.data]
    
    def set_current_frame(self, frame_idx: int):
        """Changer la frame affichée"""
        if len(self.viewer.dims.current_step) > 0:
            current_step = list(self.viewer.dims.current_step)
            current_step[0] = frame_idx
            self.viewer.dims.current_step = tuple(current_step)
    
    def reset_view(self):
        """Réinitialiser la vue (zoom, pan)"""
        self.viewer.reset_view()
