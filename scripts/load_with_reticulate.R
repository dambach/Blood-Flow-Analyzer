# Load a DICOM using Python (pydicom) via reticulate
# Usage: Rscript scripts/load_with_reticulate.R <dicom_path>

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript scripts/load_with_reticulate.R <dicom_path>")
path <- args[1]

if (!requireNamespace("reticulate", quietly = TRUE)) {
  install.packages("reticulate", repos = "https://cloud.r-project.org")
}
library(reticulate)

# Prefer project's .venv if present
venv_dir <- file.path(getwd(), ".venv")
py_bin <- file.path(venv_dir, "bin", "python")
if (file.exists(py_bin)) {
  tryCatch({
    use_python(py_bin, required = TRUE)
    message("reticulate configured to use Python: ", py_bin)
  }, error = function(e) {
    message("Could not configure reticulate to use .venv python: ", e$message)
  })
} else if (dir.exists(venv_dir)) {
  tryCatch({
    use_virtualenv(venv_dir, required = TRUE)
    message("reticulate configured to use virtualenv: ", venv_dir)
  }, error = function(e) {
    message("Could not configure reticulate to use .venv virtualenv: ", e$message)
  })
}

cat("Using reticulate Python:", reticulate::py_config()$python, "\n")

# Ensure python packages are available; try import, else install via pip
needed_py <- c("pydicom", "numpy", "Pillow", "pylibjpeg", "pylibjpeg-libjpeg")
missing_pkgs <- character(0)
for (pkg in needed_py) {
  ok <- tryCatch({
    import(pkg)
    TRUE
  }, error = function(e) FALSE)
  if (!ok) missing_pkgs <- c(missing_pkgs, pkg)
}
if (length(missing_pkgs) > 0) {
  cat("Missing python packages:", paste(missing_pkgs, collapse = ", "), "\n")
  cat("Attempting to install via reticulate::py_install(..., pip=TRUE) - this may take a while\n")
  tryCatch({
    reticulate::py_install(missing_pkgs, pip = TRUE)
  }, error = function(e) {
    cat("py_install failed:", conditionMessage(e), "\n")
    stop("Please install the missing python packages in the Python used by reticulate and re-run")
  })
}

pydicom <- import("pydicom")
np <- tryCatch(import("numpy"), error = function(e) NULL)

cat("Reading:", path, "\n")
# Force reading to tolerate some broken meta
ds <- tryCatch(pydicom$dcmread(path, force = TRUE), error = function(e) {
  stop("pydicom.dcmread failed: ", conditionMessage(e))
})

# Transfer Syntax
ts <- tryCatch({ as.character(ds$file_meta$TransferSyntaxUID) }, error = function(e) NA)
cat("TransferSyntaxUID:", ts, "\n")

# Pixel data
if (py_has_attr(ds, "pixel_array")) {
  cat("pixel_array available, attempting to convert to R and save PNG...\n")
  pixel <- tryCatch(py_to_r(ds$pixel_array), error = function(e) {
    cat("Error while retrieving pixel_array:\n", conditionMessage(e), "\n")
    NULL
  })
  if (!is.null(pixel)) {
    # normalize and save
    if (!requireNamespace("png", quietly = TRUE)) {
      install.packages("png", repos = "https://cloud.r-project.org")
    }
    out_png <- file.path(getwd(), paste0(basename(path), ".png"))
    cat("Saving preview to:", out_png, "\n")
    # If color image, ensure dimensions are height x width x channels
    if (is.numeric(pixel)) {
      maxv <- max(pixel, na.rm = TRUE)
      minv <- min(pixel, na.rm = TRUE)
      if (maxv > minv) pixel <- (pixel - minv) / (maxv - minv)
    }
    tryCatch({
      png::writePNG(pixel, out_png)
      cat("Saved PNG preview at:", out_png, "\n")
    }, error = function(e) {
      cat("Failed to write PNG:", conditionMessage(e), "\n")
    })
  }
} else {
  cat("No pixel_array attribute on dataset. Pixel data may be encapsulated or missing.\n")
}

cat("Done.\n")
