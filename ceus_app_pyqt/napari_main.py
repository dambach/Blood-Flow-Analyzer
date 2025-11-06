"""
Napari-native CEUS Analyzer - Entry Point
Full Napari version using PyQt5
"""
import sys
import os

# Force PyQt5 before any Qt imports
os.environ['QT_API'] = 'pyqt5'

from napari._qt.qt_event_loop import get_qapp
from src.ui.napari_main_window import NapariCEUSWindow


def main():
    """Launch Napari CEUS Analyzer"""
    # Get or create Qt application (shared with Napari)
    app = get_qapp()
    app.setApplicationName("CEUS Analyzer - Napari Edition")
    app.setOrganizationName("Blood Flow Analysis")
    
    # Create and show main window
    window = NapariCEUSWindow()
    window.show()
    
    # Start event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
