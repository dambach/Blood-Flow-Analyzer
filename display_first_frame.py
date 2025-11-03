#!/usr/bin/env python3
"""
Simple script to display the first frame of a CEUS DICOM file
and show mouse coordinates for easy crop/ROI coordinate selection.
"""

import sys
import numpy as np
import pydicom
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pathlib import Path


def rgb_to_grayscale(rgb_array):
    """Convert RGB array to grayscale using luminosity method."""
    return 0.299 * rgb_array[:, :, 0] + 0.587 * rgb_array[:, :, 1] + 0.114 * rgb_array[:, :, 2]


def load_first_frame(dicom_path):
    """Load the first frame from a DICOM file."""
    dcm = pydicom.dcmread(dicom_path)
    
    # Get pixel array
    pixel_array = dcm.pixel_array
    
    # Handle different array shapes
    if pixel_array.ndim == 4:
        # (frames, height, width, channels)
        first_frame = pixel_array[0, :, :, :]
    elif pixel_array.ndim == 3:
        if pixel_array.shape[0] < pixel_array.shape[1] and pixel_array.shape[0] < pixel_array.shape[2]:
            # (frames, height, width) - grayscale sequence
            first_frame = pixel_array[0, :, :]
        else:
            # (height, width, channels) - single frame
            first_frame = pixel_array
    else:
        # (height, width) - single grayscale frame
        first_frame = pixel_array
    
    # Convert to grayscale if RGB
    if first_frame.ndim == 3:
        first_frame = rgb_to_grayscale(first_frame)
    
    # Normalize to 0-1
    first_frame = (first_frame - first_frame.min()) / (first_frame.max() - first_frame.min() + 1e-8)
    
    return first_frame


class CoordinateDisplay:
    """Interactive display showing mouse coordinates."""
    
    def __init__(self, image):
        self.image = image
        self.fig, self.ax = plt.subplots(figsize=(10, 8))
        self.height, self.width = image.shape
        
        # Display image
        self.im = self.ax.imshow(image, cmap='gray', aspect='auto')
        self.ax.set_title('First Frame - Click to get coordinates\nClose window to exit', 
                         fontsize=12, pad=15)
        
        # Add colorbar
        plt.colorbar(self.im, ax=self.ax, label='Intensity')
        
        # Coordinate text
        self.coord_text = self.ax.text(0.02, 0.98, '', transform=self.ax.transAxes,
                                       verticalalignment='top',
                                       bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.8),
                                       fontsize=10)
        
        # Rectangle selection
        self.rect_start = None
        self.rect = None
        self.rect_coords = None
        
        # Connect events
        self.fig.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.fig.canvas.mpl_connect('button_press_event', self.on_mouse_press)
        self.fig.canvas.mpl_connect('button_release_event', self.on_mouse_release)
        
        # Instructions
        instructions = (
            "Instructions:\n"
            "- Move mouse to see coordinates\n"
            "- Click and drag to draw rectangle\n"
            "- Rectangle coordinates printed in console\n"
            f"Image size: {self.width} x {self.height} (width x height)"
        )
        self.ax.text(0.02, 0.02, instructions, transform=self.ax.transAxes,
                    verticalalignment='bottom',
                    bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8),
                    fontsize=9)
        
        plt.tight_layout()
    
    def on_mouse_move(self, event):
        """Update coordinate display on mouse move."""
        if event.inaxes != self.ax:
            return
        
        x, y = int(event.xdata), int(event.ydata)
        
        # Ensure coordinates are within bounds
        if 0 <= x < self.width and 0 <= y < self.height:
            intensity = self.image[y, x]
            self.coord_text.set_text(f'x={x}, y={y}\nIntensity={intensity:.3f}')
            
            # Update rectangle during drag
            if self.rect_start is not None and event.button == 1:
                x0, y0 = self.rect_start
                width = x - x0
                height = y - y0
                
                if self.rect is None:
                    self.rect = Rectangle((x0, y0), width, height, 
                                         linewidth=2, edgecolor='red', 
                                         facecolor='none', linestyle='--')
                    self.ax.add_patch(self.rect)
                else:
                    self.rect.set_width(width)
                    self.rect.set_height(height)
                
                self.fig.canvas.draw_idle()
    
    def on_mouse_press(self, event):
        """Start rectangle selection."""
        if event.inaxes != self.ax or event.button != 1:
            return
        
        # Remove previous rectangle
        if self.rect is not None:
            self.rect.remove()
            self.rect = None
        
        self.rect_start = (int(event.xdata), int(event.ydata))
    
    def on_mouse_release(self, event):
        """Finish rectangle selection and print coordinates."""
        if event.inaxes != self.ax or event.button != 1 or self.rect_start is None:
            return
        
        x0, y0 = self.rect_start
        x1, y1 = int(event.xdata), int(event.ydata)
        
        # Ensure coordinates are ordered (min, max)
        x_min, x_max = min(x0, x1), max(x0, x1)
        y_min, y_max = min(y0, y1), max(y0, y1)
        
        # Ensure within bounds
        x_min = max(0, x_min)
        x_max = min(self.width - 1, x_max)
        y_min = max(0, y_min)
        y_max = min(self.height - 1, y_max)
        
        self.rect_coords = (x_min, x_max, y_min, y_max)
        
        # Print coordinates
        print("\n" + "="*60)
        print("RECTANGLE COORDINATES:")
        print(f"  x_min = {x_min},  x_max = {x_max}  (width = {x_max - x_min})")
        print(f"  y_min = {y_min},  y_max = {y_max}  (height = {y_max - y_min})")
        print("\nFor NumPy array slicing:")
        print(f"  cropped = frame[{y_min}:{y_max}, {x_min}:{x_max}]")
        print("="*60 + "\n")
        
        self.rect_start = None
    
    def show(self):
        """Display the interactive plot."""
        plt.show()


def main():
    """Main function."""
    # Get DICOM file path
    if len(sys.argv) > 1:
        dicom_path = sys.argv[1]
    else:
        # Default path
        dicom_path = "data/dicom_file"
    
    dicom_path = Path(dicom_path)
    
    if not dicom_path.exists():
        print(f"Error: File not found: {dicom_path}")
        print("\nUsage: python display_first_frame.py [path_to_dicom_file]")
        print(f"Default path: data/dicom_file")
        sys.exit(1)
    
    print(f"Loading DICOM file: {dicom_path}")
    
    try:
        # Load first frame
        first_frame = load_first_frame(dicom_path)
        print(f"Image loaded successfully!")
        print(f"Image size: {first_frame.shape[1]} x {first_frame.shape[0]} (width x height)")
        print(f"Intensity range: {first_frame.min():.3f} to {first_frame.max():.3f}")
        
        # Display interactive plot
        display = CoordinateDisplay(first_frame)
        display.show()
        
    except Exception as e:
        print(f"Error loading DICOM file: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
