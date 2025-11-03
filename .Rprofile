# .Rprofile - Configure reticulate to use project's .venv on startup
# This ensures that Python packages from .venv are available in all R sessions

# Detect and configure .venv if present
venv_dir <- file.path(getwd(), ".venv")
py_bin <- file.path(venv_dir, "bin", "python")

if (file.exists(py_bin)) {
  message("[.Rprofile] Configuring reticulate to use .venv python: ", py_bin)
  tryCatch({
    # Load reticulate
    if (!requireNamespace("reticulate", quietly = TRUE)) {
      install.packages("reticulate", repos = "https://cloud.r-project.org", quiet = TRUE)
    }
    library(reticulate)
    # Configure to use project's .venv
    use_python(py_bin, required = TRUE)
    message("[.Rprofile] SUCCESS: Python configured to use .venv")
  }, error = function(e) {
    message("[.Rprofile] WARNING: Could not configure reticulate with .venv: ", e$message)
  })
} else if (dir.exists(venv_dir)) {
  message("[.Rprofile] Detected .venv directory but no python binary; attempting use_virtualenv()")
  tryCatch({
    if (!requireNamespace("reticulate", quietly = TRUE)) {
      install.packages("reticulate", repos = "https://cloud.r-project.org", quiet = TRUE)
    }
    library(reticulate)
    use_virtualenv(venv_dir, required = TRUE)
    message("[.Rprofile] SUCCESS: Python configured to use .venv virtualenv")
  }, error = function(e) {
    message("[.Rprofile] WARNING: Could not configure virtualenv: ", e$message)
  })
}
