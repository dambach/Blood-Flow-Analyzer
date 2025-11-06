"""
ROI management panel
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QListWidget, QLabel, QLineEdit, QColorDialog
)
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor


class ROIPanel(QWidget):
    """Panel for managing ROIs"""
    
    roi_added = pyqtSignal(str)  # ROI label
    roi_removed = pyqtSignal(str)
    roi_selected = pyqtSignal(str)
    
    def __init__(self, roi_manager, parent=None):
        super().__init__(parent)
        
        self.roi_manager = roi_manager
        
        self._create_widgets()
        self._create_layout()
        self._connect_signals()
    
    def _create_widgets(self):
        """Create widgets"""
        # ROI list
        self.roi_list = QListWidget()
        
        # Controls
        self.btn_add = QPushButton("➕ Add ROI")
        self.btn_remove = QPushButton("❌ Remove")
        self.btn_clear = QPushButton("🗑️ Clear All")
        
        # ROI label input
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("ROI label (auto if empty)")
    
    def _create_layout(self):
        """Create layout"""
        layout = QVBoxLayout()
        
        # Header
        layout.addWidget(QLabel("<b>Region of Interest Manager</b>"))
        
        # ROI list
        layout.addWidget(QLabel("Active ROIs:"))
        layout.addWidget(self.roi_list)
        
        # Label input
        label_layout = QHBoxLayout()
        label_layout.addWidget(QLabel("Label:"))
        label_layout.addWidget(self.label_input)
        layout.addLayout(label_layout)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)
        
        layout.addStretch()
        
        self.setLayout(layout)
    
    def _connect_signals(self):
        """Connect signals"""
        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        self.roi_list.itemClicked.connect(self._on_item_clicked)
    
    def _on_add_clicked(self):
        """Handle add button click"""
        # Signal main window to enable drawing mode
        label = self.label_input.text().strip() or None
        # Note: Drawing is handled by InteractiveImageLabel in main window
        # This button is kept for future manual ROI addition if needed
    
    def _on_remove_clicked(self):
        current_item = self.roi_list.currentItem()
        if current_item:
            label = current_item.text().split(' (')[0]
            if self.roi_manager.remove_roi(label):
                self.refresh_list()
                self.roi_removed.emit(label)
    
    def _on_clear_clicked(self):
        """Handle clear all button click"""
        for roi in list(self.roi_manager.rois):
            self.roi_removed.emit(roi.label)
        self.roi_manager.clear()
        self.refresh_list()
    
    def _on_item_clicked(self, item):
        """Handle ROI list item click"""
        # Extract label from item text (format: "label (WxH px)")
        label = item.text().split(' (')[0]
        self.roi_selected.emit(label)
    
    def refresh_list(self):
        self.roi_list.clear()
        for roi in self.roi_manager.rois:
            item_text = f"{roi.label} ({roi.n_points} pts, {roi.area:.0f} px²)"
            self.roi_list.addItem(item_text)

