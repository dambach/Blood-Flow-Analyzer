#!/usr/bin/env Rscript
# Test the frame rendering with actual plot generation

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

# Store as 4D array (641 x 540 x 720 x 3)
frames_r <- array(as.numeric(pix), dim = dim(pix))
cat("[TEST] Loaded frames shape:", paste(dim(frames_r), collapse = " x "), "\n")

# Simulate the render plot function
cat("\n[TEST] Testing frame rendering...\n")

tryCatch({
  idx <- 1
  d <- dim(frames_r)
  cat("[TEST] frames_r dimensions:", paste(d, collapse = " x "), "\n")
  
  if (length(d) == 3) {
    frame <- frames_r[idx, , ]
  } else if (length(d) == 4) {
    frame <- frames_r[idx, , , ]
  } else {
    stop("Invalid dimensions")
  }
  
  cat("[TEST] Extracted frame shape:", paste(dim(frame), collapse = " x "), "\n")
  
  # Test the rendering logic
  if (length(dim(frame)) == 3 && dim(frame)[3] >= 3) {
    cat("[TEST] Detected 3-channel RGB image\n")
    img <- frame
    # Normalize to 0..1
    img <- img - min(img, na.rm = TRUE)
    mx <- max(img, na.rm = TRUE)
    if (mx > 0) img <- img / mx
    cat("[TEST] Normalized image shape:", paste(dim(img), collapse = " x "), "\n")
    
    h <- dim(img)[1]
    w <- dim(img)[2]
    cat("[TEST] Image dimensions: ", h, "x", w, "\n")
    
    # Test as.raster conversion
    cat("[TEST] Converting to raster...\n")
    raster_img <- as.raster(array(c(img[,,1], img[,,2], img[,,3]), dim = c(h, w, 3)))
    cat("[TEST] Raster created successfully\n")
    cat("[TEST] Raster class:", class(raster_img), "\n")
    cat("[TEST] Raster dimensions:", paste(dim(raster_img), collapse = " x "), "\n")
  }
  
  cat("[TEST] SUCCESS: Frame rendering logic passed!\n")
}, error = function(e) {
  cat("[ERROR] Frame rendering failed:\n")
  print(e)
  quit(status = 1)
})
