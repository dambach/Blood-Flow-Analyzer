#!/usr/bin/env python3
"""
Quick launch script for CEUS Analyzer
Run from repository root: python ceus_app_pyqt/launch.py
"""
import sys
from pathlib import Path

# Add parent directory to path to make 'src' importable as a package
app_dir = Path(__file__).parent
sys.path.insert(0, str(app_dir))

# Launch application
if __name__ == "__main__":
    from src.main import main
    main()
