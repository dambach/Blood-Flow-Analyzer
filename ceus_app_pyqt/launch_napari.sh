#!/bin/bash
# Launch script for Napari CEUS Analyzer
# Activates .venv and runs the Napari version

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 CEUS Analyzer - Napari Edition${NC}"
echo "=================================="

# Check if .venv exists
if [ ! -d "$REPO_ROOT/.venv" ]; then
    echo -e "${RED}❌ Error: .venv not found at $REPO_ROOT/.venv${NC}"
    echo "Please create a virtual environment first:"
    echo "  python -m venv .venv"
    exit 1
fi

# Activate virtual environment
echo -e "${YELLOW}📦 Activating virtual environment...${NC}"
source "$REPO_ROOT/.venv/bin/activate"

# Check if napari is installed
if ! python -c "import napari" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Napari not found. Installing dependencies...${NC}"
    pip install -r "$SCRIPT_DIR/requirements.txt"
fi

# Check if PyQt5 is installed
if ! python -c "import PyQt5" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  PyQt5 not found. Installing...${NC}"
    pip install PyQt5
fi

# Check if pyqtgraph is installed
if ! python -c "import pyqtgraph" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  pyqtgraph not found. Installing...${NC}"
    pip install pyqtgraph
fi

# Launch application
echo -e "${GREEN}✨ Launching Napari CEUS Analyzer...${NC}"
cd "$SCRIPT_DIR"
python napari_main.py

# Deactivate on exit
deactivate
