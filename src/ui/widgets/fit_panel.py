"""
Fit parameters panel (inspired by app.R)
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox,
    QDoubleSpinBox, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox
)
from PyQt5.QtCore import pyqtSignal


class FitPanel(QWidget):
    """Panel for wash-in model fit parameters and results"""
    
    fit_requested = pyqtSignal(dict)  # Emit fit parameters
    interval_use_toggled = pyqtSignal(bool)  # Reflects "Limit fit to selected time interval"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._create_widgets()
        self._create_layout()
        self._connect_signals()
    
    def _create_widgets(self):
        """Create widgets"""
        # Start values
        self.a_start_spin = QDoubleSpinBox()
        self.a_start_spin.setRange(0.0, 10000.0)
        self.a_start_spin.setValue(100.0)
        self.a_start_spin.setSingleStep(10.0)
        
        self.b_start_spin = QDoubleSpinBox()
        self.b_start_spin.setRange(0.0, 10.0)
        self.b_start_spin.setValue(0.5)
        self.b_start_spin.setSingleStep(0.1)
        self.b_start_spin.setDecimals(3)
        
        # Bounds (Lower)
        self.a_lower_spin = QDoubleSpinBox()
        self.a_lower_spin.setRange(0.0, 10000.0)
        self.a_lower_spin.setValue(0.0)
        
        self.b_lower_spin = QDoubleSpinBox()
        self.b_lower_spin.setRange(0.0, 10.0)
        self.b_lower_spin.setValue(0.1)
        self.b_lower_spin.setDecimals(3)
        
        # Bounds (Upper)
        self.a_upper_spin = QDoubleSpinBox()
        self.a_upper_spin.setRange(0.0, 100000.0)
        self.a_upper_spin.setValue(10000.0)
        self.a_upper_spin.setSpecialValueText("Inf")
        
        self.b_upper_spin = QDoubleSpinBox()
        self.b_upper_spin.setRange(0.0, 10.0)
        self.b_upper_spin.setValue(5.0)
        self.b_upper_spin.setDecimals(3)
        
        # Fit window
        self.chk_use_plot_interval = QCheckBox("Limit fit to selected time interval")
        try:
            self.chk_use_plot_interval.setToolTip("Enable the time interval selector on the TIC plot and restrict fitting to that range")
        except Exception:
            pass
        self.t_max_spin = QDoubleSpinBox()
        self.t_max_spin.setRange(0.1, 60.0)
        self.t_max_spin.setValue(5.0)
        self.t_max_spin.setSuffix(" s")
        
        # Fit button
        self.btn_fit = QPushButton("🔬 Fit Model")
        self.btn_fit.setStyleSheet("font-weight: bold; padding: 10px;")
        
        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(2)
        self.results_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setAlternatingRowColors(True)
    
    def _create_layout(self):
        """Create layout"""
        layout = QVBoxLayout()
        
        # Header
        layout.addWidget(QLabel("<b>Wash-in Model Parameters</b>"))
        
        # Start values
        start_group = QGroupBox("Start Values")
        start_layout = QFormLayout()
        start_layout.addRow("A (plateau):", self.a_start_spin)
        start_layout.addRow("B (rate):", self.b_start_spin)
        start_group.setLayout(start_layout)
        layout.addWidget(start_group)
        
        # Bounds
        bounds_group = QGroupBox("Bounds")
        bounds_layout = QFormLayout()
        bounds_layout.addRow("A lower:", self.a_lower_spin)
        bounds_layout.addRow("A upper:", self.a_upper_spin)
        bounds_layout.addRow("B lower:", self.b_lower_spin)
        bounds_layout.addRow("B upper:", self.b_upper_spin)
        bounds_group.setLayout(bounds_layout)
        layout.addWidget(bounds_group)
        
        # Fit window
        window_group = QGroupBox("Fit Window")
        window_layout = QFormLayout()
        window_layout.addRow(self.chk_use_plot_interval)
        window_layout.addRow("t_max:", self.t_max_spin)
        window_group.setLayout(window_layout)
        layout.addWidget(window_group)
        
        # Fit button
        layout.addWidget(self.btn_fit)
        
        # Results
        layout.addWidget(QLabel("<b>Fit Results</b>"))
        layout.addWidget(self.results_table)
        
        layout.addStretch()
        
        self.setLayout(layout)
    
    def _connect_signals(self):
        """Connect signals"""
        self.btn_fit.clicked.connect(self._on_fit_clicked)
        try:
            self.chk_use_plot_interval.toggled.connect(self.interval_use_toggled.emit)
        except Exception:
            pass
    
    def _on_fit_clicked(self):
        """Handle fit button click"""
        params = {
            'A_start': self.a_start_spin.value(),
            'B_start': self.b_start_spin.value(),
            'bounds': (
                (self.a_lower_spin.value(), self.b_lower_spin.value()),
                (self.a_upper_spin.value(), self.b_upper_spin.value())
            ),
            't_max': self.t_max_spin.value()
        }
        self.fit_requested.emit(params)
    
    def display_results(self, results: dict):
        """
        Display fit results in table
        
        Args:
            results: Dictionary of metric names and values
        """
        self.results_table.setRowCount(len(results))
        
        for i, (metric, value) in enumerate(results.items()):
            self.results_table.setItem(i, 0, QTableWidgetItem(metric))
            
            if isinstance(value, float):
                value_str = f"{value:.4f}" if not np.isnan(value) else "N/A"
            else:
                value_str = str(value)
            
            self.results_table.setItem(i, 1, QTableWidgetItem(value_str))
        
        self.results_table.resizeColumnsToContents()


# Import numpy for nan check
import numpy as np
