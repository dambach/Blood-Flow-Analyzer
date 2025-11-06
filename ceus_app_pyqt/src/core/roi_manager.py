"""
ROI (Region of Interest) management module
"""
import numpy as np
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass, field
from src.utils.validators import validate_roi


@dataclass
class ROI:
    """Region of Interest polygone"""
    def __init__(self, label, polygon, color=(255,0,0), visible=True, metadata=None):
        self.label = label
        self.polygon = polygon  # Liste de points [(x, y), ...]
        self.color = color
        self.visible = visible
        self.metadata = metadata or {}
    @property
    def area(self) -> float:
        # Aire du polygone (algorithme de Shoelace)
        x = [pt[0] for pt in self.polygon]
        y = [pt[1] for pt in self.polygon]
        return 0.5 * abs(sum(x[i]*y[(i+1)%len(y)] - x[(i+1)%len(x)]*y[i] for i in range(len(self.polygon))))
    @property
    def n_points(self) -> int:
        return len(self.polygon)
    @property
    def center(self) -> tuple:
        x = [pt[0] for pt in self.polygon]
        y = [pt[1] for pt in self.polygon]
        return (sum(x)/len(x), sum(y)/len(y))


class ROIManager:
    """Manage multiple labeled ROIs"""
    
    def __init__(self):
        self.rois: List[ROI] = []
        self._next_id = 1
    
    def add_roi(self, polygon: list, label: Optional[str] = None, color: Optional[tuple] = None) -> ROI:
        """Ajoute un polygone ROI"""
        if label is None:
            label = f"ROI_{self._next_id}"
            self._next_id += 1
        if color is None:
            colors = [
                (255, 0, 0),    # Red
                (0, 255, 0),    # Green
                (0, 0, 255),    # Blue
                (255, 255, 0),  # Yellow
                (255, 0, 255),  # Magenta
                (0, 255, 255),  # Cyan
                (255, 128, 0),  # Orange
                (128, 0, 255),  # Purple
            ]
            color = colors[len(self.rois) % len(colors)]
        roi = ROI(label=label, polygon=polygon, color=color)
        self.rois.append(roi)
        return roi
    
    def remove_roi(self, label: str) -> bool:
        """
        Remove ROI by label
        
        Args:
            label: ROI label
            
        Returns:
            True if removed, False if not found
        """
        for i, roi in enumerate(self.rois):
            if roi.label == label:
                self.rois.pop(i)
                return True
        return False

    def rename_roi(self, old_label: str, new_label: str) -> bool:
        """Rename an ROI if label exists and new label not used.
        Returns True on success.
        """
        if any(r.label == new_label for r in self.rois):
            return False
        roi = self.get_roi(old_label)
        if roi is None:
            return False
        roi.label = new_label
        return True
    
    def get_roi(self, label: str) -> Optional[ROI]:
        """Get ROI by label"""
        for roi in self.rois:
            if roi.label == label:
                return roi
        return None
    
    def get_all_visible(self) -> List[ROI]:
        """Get all visible ROIs"""
        return [roi for roi in self.rois if roi.visible]
    
    def clear(self):
        """Remove all ROIs"""
        self.rois.clear()
        self._next_id = 1
    
    def validate_rois(self, image_shape: Tuple[int, int]) -> Dict[str, bool]:
        # Valide que tous les points du polygone sont dans l'image
        h, w = image_shape
        results = {}
        for roi in self.rois:
            valid = all(0 <= x < w and 0 <= y < h for x, y in roi.polygon)
            results[roi.label] = valid
        return results
    
    def __len__(self) -> int:
        """Number of ROIs"""
        return len(self.rois)
    
    def __iter__(self):
        """Iterate over ROIs"""
        return iter(self.rois)
