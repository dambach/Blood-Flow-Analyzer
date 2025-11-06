"""
DICOM loading and region extraction module
Extracts B-mode and CEUS stacks from DICOM files (GE + SuperSonic compatible)
"""
import numpy as np
import pydicom
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from src.utils.converters import ycbcr_to_rgb


def _color_variance(stack: np.ndarray) -> float:
    """Calculate color variance for region classification"""
    if stack.ndim == 4 and stack.shape[-1] == 3:
        frame_idx = min(len(stack) // 2, len(stack) - 1)
        frame = stack[frame_idx]
        r, g, b = frame[..., 0], frame[..., 1], frame[..., 2]
        
        rg_var = np.std(r.astype(float) - g.astype(float))
        gb_var = np.std(g.astype(float) - b.astype(float))
        rb_var = np.std(r.astype(float) - b.astype(float))
        
        return float(rg_var + gb_var + rb_var)
    return 0.0


class DICOMLoader:
    """DICOM file loader with B-mode/CEUS region extraction"""
    
    def __init__(self, dicom_path: Path):
        """
        Initialize DICOM loader
        
        Args:
            dicom_path: Path to DICOM file or directory
        """
        self.dicom_path = Path(dicom_path)
        self.ds: Optional[pydicom.Dataset] = None
        self.metadata: Dict[str, Any] = {}
        self.scanner_info: Dict[str, Any] = {}
        
        self.bmode_stack: Optional[np.ndarray] = None
        self.ceus_stack: Optional[np.ndarray] = None
        self.bmode_region_idx: Optional[int] = None
        self.ceus_region_idx: Optional[int] = None
        
    def load(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Load DICOM and extract B-mode/CEUS stacks
        
        Returns:
            Tuple (bmode_stack, ceus_stack)
        """
        # Find DICOM file
        if self.dicom_path.is_dir():
            files = sorted([p for p in self.dicom_path.glob('*') if p.is_file()])
            if not files:
                raise FileNotFoundError(f"No file found in {self.dicom_path}")
            self.dicom_path = files[0]
        
        # Read DICOM
        self.ds = pydicom.dcmread(str(self.dicom_path), force=True)
        
        # Extract metadata
        self.metadata = {
            'Rows': getattr(self.ds, 'Rows', None),
            'Columns': getattr(self.ds, 'Columns', None),
            'NumberOfFrames': getattr(self.ds, 'NumberOfFrames', None),
            'PhotometricInterpretation': getattr(self.ds, 'PhotometricInterpretation', None),
            'CineRate': getattr(self.ds, 'CineRate', None),
            'FrameTime': getattr(self.ds, 'FrameTime', None),
            'RecommendedDisplayFrameRate': getattr(self.ds, 'RecommendedDisplayFrameRate', None),
        }
        
        self.scanner_info = {
            'Manufacturer': getattr(self.ds, 'Manufacturer', None),
            'ManufacturerModelName': getattr(self.ds, 'ManufacturerModelName', None),
            'InstitutionName': getattr(self.ds, 'InstitutionName', None),
        }
        
        # Extract pixel array
        arr = self.ds.pixel_array
        
        # Extract regions
        self._extract_regions(arr)
        
        return self.bmode_stack, self.ceus_stack
    
    def _extract_regions(self, arr: np.ndarray):
        """Extract B-mode and CEUS from DICOM regions"""
        regions = getattr(self.ds, 'SequenceOfUltrasoundRegions', None)
        
        if regions is None or len(regions) == 0:
            # Fallback: use entire array as CEUS
            self.ceus_stack = self._convert_colorspace(arr)
            return
        
        # Parse all regions
        all_regions = []
        for i, reg in enumerate(regions):
            dtype = getattr(reg, 'RegionDataType', None)
            flags = getattr(reg, 'RegionFlags', None)
            x0 = getattr(reg, 'RegionLocationMinX0', None)
            y0 = getattr(reg, 'RegionLocationMinY0', None)
            x1 = getattr(reg, 'RegionLocationMaxX1', None)
            y1 = getattr(reg, 'RegionLocationMaxY1', None)
            
            if None in [x0, y0, x1, y1]:
                continue
            
            # Clip coordinates
            H, W = arr.shape[1], arr.shape[2]
            x0 = max(0, min(int(x0), W - 1))
            y0 = max(0, min(int(y0), H - 1))
            x1 = max(0, min(int(x1), W - 1))
            y1 = max(0, min(int(y1), H - 1))
            
            if x0 >= x1 or y0 >= y1:
                continue
            
            # Extract region
            if arr.ndim == 4:
                region_stack = arr[:, y0:y1+1, x0:x1+1, :]
            else:
                region_stack = arr[:, y0:y1+1, x0:x1+1]
            
            all_regions.append((i, dtype, flags, x0, region_stack))
        
        # Classify regions
        self._classify_regions(all_regions)
    
    def _classify_regions(self, all_regions: list):
        """Classify regions as B-mode or CEUS (GE = position, others = color variance)"""
        manufacturer = getattr(self.ds, 'Manufacturer', '').lower()
        
        # Separate by DataType
        type2_regions = [(idx, stack) for idx, dtype, flags, x0, stack in all_regions if dtype == 2]
        type1_regions = [(idx, flags, x0, stack) for idx, dtype, flags, x0, stack in all_regions if dtype == 1]
        
        # Case 1: Explicit CEUS (DataType=2)
        if len(type2_regions) > 0:
            self.ceus_region_idx, ceus_stack = type2_regions[0]
            self.ceus_stack = self._convert_colorspace(ceus_stack)
            
            if len(type1_regions) > 0:
                self.bmode_region_idx, _, _, bmode_stack = type1_regions[0]
                self.bmode_stack = self._convert_colorspace(bmode_stack)
            return
        
        # Case 2: Split-screen (2× DataType=1)
        if len(type1_regions) >= 2:
            if 'ge' in manufacturer:
                # GE: classify by position (rightmost = CEUS)
                sorted_regions = sorted(type1_regions, key=lambda x: x[2])
                self.bmode_region_idx, _, _, bmode_stack = sorted_regions[0]
                self.ceus_region_idx, _, _, ceus_stack = sorted_regions[1]
            else:
                # Others: classify by color variance (highest = CEUS)
                scores = [(idx, x0, stack, _color_variance(stack))
                         for idx, flags, x0, stack in type1_regions]
                scores.sort(key=lambda x: x[3], reverse=True)
                
                self.ceus_region_idx, _, ceus_stack, _ = scores[0]
                self.bmode_region_idx, _, bmode_stack, _ = scores[1]
            
            self.ceus_stack = self._convert_colorspace(ceus_stack)
            self.bmode_stack = self._convert_colorspace(bmode_stack)
            return
        
        # Case 3: Single region → treat as CEUS
        if len(all_regions) == 1:
            self.ceus_region_idx = all_regions[0][0]
            self.ceus_stack = self._convert_colorspace(all_regions[0][4])
    
    def _convert_colorspace(self, stack: np.ndarray) -> np.ndarray:
        """Convert YBR to RGB if needed"""
        photo = getattr(self.ds, 'PhotometricInterpretation', None)
        
        if photo and 'YBR' in str(photo) and stack.ndim == 4:
            return np.stack([ycbcr_to_rgb(f) for f in stack], axis=0)
        
        return stack
    
    def get_fps(self) -> float:
        """Calculate frames per second"""
        if self.metadata.get('FrameTime') is not None:
            return 1000.0 / self.metadata['FrameTime']
        elif self.metadata.get('CineRate') is not None:
            return self.metadata['CineRate']
        elif self.metadata.get('RecommendedDisplayFrameRate') is not None:
            return self.metadata['RecommendedDisplayFrameRate']
        else:
            # Fallback estimate (assume 60s total)
            if self.ceus_stack is not None:
                return len(self.ceus_stack) / 60.0
            return 10.0  # Default guess
