"""
CEUS Analyzer - Main entry point
"""
import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from src.ui.main_window import CEUSMainWindow


def main():
    """Launch CEUS Analyzer application"""
    # Enable High DPI scaling (PyQt5 way)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    app.setApplicationName("CEUS Analyzer")
    app.setOrganizationName("Blood Flow Analysis")
    
    # Load stylesheet
    style_path = Path(__file__).parent.parent / "resources" / "styles" / "app.qss"
    if style_path.exists():
        with open(style_path, 'r') as f:
            app.setStyleSheet(f.read())
    
    # Create and show main window
    window = CEUSMainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
