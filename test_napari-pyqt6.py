import sys
import numpy as np
import os

# IMPORTANT : utiliser le même backend pour tout
os.environ["QT_API"] = "pyqt5"

from qtpy.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from qtpy.QtCore import Qt
import napari


class NapariInQtWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Napari embedded + polygon ROI")
        self.resize(1200, 800)

        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        info = QLabel(
            "Dessine un polygone avec l'outil Shapes.\n"
            "Les coordonnées seront affichées dans la console."
        )
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        # Créer un viewer napari SANS sa boucle propre
        self.viewer = napari.Viewer(show=False)

        # Widget Qt interne du viewer
        qt_viewer_widget = self.viewer.window._qt_viewer
        layout.addWidget(qt_viewer_widget, stretch=1)

        # Image de test
        img = np.random.rand(256, 256)
        self.viewer.add_image(img, name="random")

        # Couche Shapes pour ROI
        self._add_polygon_layer()

    def _add_polygon_layer(self):
        self.roi_layer = self.viewer.add_shapes(
            name="ROIs",
            shape_type="polygon",
            edge_color="yellow",
            face_color=[1.0, 1.0, 0.0, 0.2],
            edge_width=2,
        )
        self.roi_layer.mode = "add_polygon"

        @self.roi_layer.events.data.connect
        def _on_data_changed(event):
            if len(self.roi_layer.data) == 0:
                return
            poly = np.array(self.roi_layer.data[-1])
            print("\nNouveau/MAJ ROI polygone")
            print(f"Nombre de points : {poly.shape[0]}")
            print("Coordonnées (y, x) :")
            print(poly)


def main():
    app = QApplication(sys.argv)
    win = NapariInQtWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()