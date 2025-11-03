#!/usr/bin/env Rscript
# Test script with the actual DICOM file that exists

library(reticulate)

# Configure Python
venv_path <- file.path(getwd(), ".venv", "bin", "python")
if (file.exists(venv_path)) {
  use_python(venv_path, required = TRUE)
  cat("[TEST] Python configured to use .venv\n")
}

# Load required packages
cat("[TEST] Importing pydicom and numpy...\n")
pydicom <- import("pydicom")
np <- import("numpy")

# Load DICOM - using the actual file that exists
dicom_path <- "data/dicom_file"
if (!file.exists(dicom_path)) {
  cat("[ERROR] DICOM file not found:", dicom_path, "\n")
  quit(status = 1)
}

cat("[TEST] Loading DICOM from:", dicom_path, "\n")
cat("[TEST] File size:", file.size(dicom_path) / 1e9, "GB\n")

tryCatch({
  ds <- pydicom$dcmread(dicom_path, force = TRUE)
  cat("[TEST] DICOM loaded successfully\n")
}, error = function(e) {
  cat("[ERROR] Failed to load DICOM:\n")
  print(e)
  quit(status = 1)
})

# Get pixel_array
cat("[TEST] Accessing pixel_array...\n")
tryCatch({
  pix <- py_to_r(ds$pixel_array)
  cat("[TEST] pixel_array shape:", paste(dim(pix), collapse = " x "), "\n")
}, error = function(e) {
  cat("[ERROR] Failed to get pixel_array:\n")
  print(e)
  quit(status = 1)
})

# Normalize shape
dims <- dim(pix)
cat("[TEST] Number of dimensions:", length(dims), "\n")

# Recreate the exact logic from the app
to_numeric <- function(x) {
  x <- as.numeric(x)
  x
}

if (length(dims) == 2) {
  cat("[TEST] 2D array detected - single frame grayscale\n")
  frames_r <- array(to_numeric(pix), dim = c(1, dims[1], dims[2]))
} else if (length(dims) == 3) {
  cat("[TEST] 3D array detected\n")
  if (dims[1] > 1 && dims[3] <= 4) {
    cat("[TEST]   Interpreting as: frames x rows x cols\n")
    frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
  } else if (dims[3] <= 4 && dims[1] > 1 && dims[2] > 1) {
    cat("[TEST]   Ambiguous 3D - interpreting as: frames x rows x cols\n")
    frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
  } else if (dims[3] > 4) {
    cat("[TEST]   Interpreting as: frames x rows x cols\n")
    frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
  } else {
    cat("[TEST]   Default: frames x rows x cols\n")
    frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
  }
} else if (length(dims) == 4) {
  cat("[TEST] 4D array detected - frames x rows x cols x channels\n")
  frames_r <- array(to_numeric(pix), dim = dims)
} else {
  cat("[ERROR] Unhandled pixel_array dims:", paste(dims, collapse = ","), "\n")
  quit(status = 1)
}

cat("[TEST] Normalized frames shape:", paste(dim(frames_r), collapse = " x "), "\n")
nframes <- dim(frames_r)[1]
cat("[TEST] Number of frames:", nframes, "\n")

# Test frame extraction (this is where the error happens)
cat("\n[TEST] Testing frame extraction...\n")
idx <- 1
d <- dim(frames_r)
cat("[TEST] frames_r dimensions:", paste(d, collapse = " x "), "\n")
cat("[TEST] Number of dimensions:", length(d), "\n")

if (length(d) == 3) {
  cat("[TEST] Extracting frame using [idx, , ]\n")
  tryCatch({
    frame <- frames_r[idx, , ]
    cat("[TEST] SUCCESS: Frame extracted, shape:", paste(dim(frame), collapse = " x "), "\n")
  }, error = function(e) {
    cat("[ERROR] Failed to extract frame:\n")
    print(e)
    quit(status = 1)
  })
} else if (length(d) == 4) {
  cat("[TEST] Extracting frame using [idx, , , ]\n")
  tryCatch({
    frame <- frames_r[idx, , , ]
    cat("[TEST] SUCCESS: Frame extracted, shape:", paste(dim(frame), collapse = " x "), "\n")
  }, error = function(e) {
    cat("[ERROR] Failed to extract frame:\n")
    print(e)
    quit(status = 1)
  })
}

cat("\n[TEST] All tests passed!\n")
