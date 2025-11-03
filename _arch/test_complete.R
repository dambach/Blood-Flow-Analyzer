#!/usr/bin/env Rscript
# Complete test including crop and ROI logic

library(reticulate)

# Configure Python
venv_path <- file.path(getwd(), ".venv", "bin", "python")
if (file.exists(venv_path)) {
  use_python(venv_path, required = TRUE)
}

# Load required packages
pydicom <- import("pydicom")
np <- import("numpy")

# Load DICOM
dicom_path <- "data/dicom_file"
ds <- pydicom$dcmread(dicom_path, force = TRUE)
pix <- py_to_r(ds$pixel_array)

cat("[TEST] Loaded DICOM with shape:", paste(dim(pix), collapse = " x "), "\n")

# Store as 4D array
frames_r <- array(as.numeric(pix), dim = dim(pix))
cat("[TEST] frames_r shape:", paste(dim(frames_r), collapse = " x "), "\n")

# Simulate crop operation
cat("\n[TEST] Testing crop operation...\n")
d <- dim(frames_r)
cat("[TEST] Array dimensions:", paste(d, collapse = " x "), "\n")

# Simulate brush coordinates
x0 <- 100; x1 <- 300
y0 <- 150; y1 <- 350
cat("[TEST] Crop region: x[", x0, ":", x1, "], y[", y0, ":", y1, "]\n")

tryCatch({
  if (length(d) == 3) {
    cropped <- frames_r[, y0:y1, x0:x1, drop = FALSE]
    cat("[TEST] Cropped using 3D indexing\n")
  } else if (length(d) == 4) {
    cropped <- frames_r[, y0:y1, x0:x1, , drop = FALSE]
    cat("[TEST] Cropped using 4D indexing\n")
  }
  cat("[TEST] SUCCESS: Cropped shape:", paste(dim(cropped), collapse = " x "), "\n")
}, error = function(e) {
  cat("[ERROR] Crop failed:\n")
  print(e)
  quit(status = 1)
})

# Test ROI extraction and TIC computation
cat("\n[TEST] Testing ROI extraction and TIC computation...\n")
roi_x0 <- 20; roi_x1 <- 50
roi_y0 <- 30; roi_y1 <- 70

frames <- cropped
d <- dim(frames)
n <- d[1]
cat("[TEST] Computing TIC for", n, "frames...\n")

tryCatch({
  tic <- numeric(n)
  for (i in seq_len(min(n, 5))) {  # Test with first 5 frames
    # Extract frame i
    if (length(d) == 3) {
      frame_2d <- frames[i, , ]
    } else if (length(d) == 4) {
      frame_3d <- frames[i, , , ]
      # Convert to grayscale
      if (dim(frame_3d)[3] >= 3) {
        frame_2d <- frame_3d[,,1]*0.299 + frame_3d[,,2]*0.587 + frame_3d[,,3]*0.114
      } else {
        frame_2d <- frame_3d[,,1]
      }
    }
    
    # Extract ROI and compute mean
    sub <- frame_2d[roi_y0:roi_y1, roi_x0:roi_x1]
    tic[i] <- mean(sub, na.rm = TRUE)
    cat("[TEST] Frame", i, "TIC value:", tic[i], "\n")
  }
  cat("[TEST] SUCCESS: TIC computation passed!\n")
}, error = function(e) {
  cat("[ERROR] TIC computation failed:\n")
  print(e)
  quit(status = 1)
})

cat("\n[TEST] All operations passed!\n")
