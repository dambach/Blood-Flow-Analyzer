#!/usr/bin/env Rscript
library(shiny)
library(reticulate)

# Note: Python is configured by .Rprofile to use .venv before app startup.
# No additional configuration needed here.

# Simple Shiny app to: load DICOM via pydicom (reticulate), crop first frame and
# apply crop to all frames, play the cropped clip, select flash frame with slider,
# draw an ROI on the first cropped frame and compute intensity over time (TIC).

ui <- fluidPage(
  titlePanel("DICOM crop / ROI / TIC (reticulate + pydicom)"),
  sidebarLayout(
    sidebarPanel(
      textInput("dicom_path", "DICOM file or directory", value = "data/dicom_file"),
      actionButton("load_btn", "Load DICOM"),
      hr(),
      actionButton("apply_crop", "Apply crop from brush"),
      actionButton("reset_crop", "Reset crop"),
      hr(),
      actionButton("play_btn", "Play"),
      sliderInput("frame_slider", "Frame", min = 1, max = 1, value = 1, step = 1, animate = FALSE),
      hr(),
      actionButton("capture_roi", "Capture ROI from brush"),
      actionButton("clear_roi", "Clear ROI"),
      hr(),
      downloadButton("download_tic", "Download TIC CSV")
    ),
    mainPanel(
      h4("Instructions:"),
      tags$ul(
        tags$li("Enter path to DICOM file (single file) or directory containing DICOM files."),
        tags$li("Load, then draw a rectangle on the image (use the mouse drag brush) and click 'Apply crop' to crop all frames."),
        tags$li("Use Play or the slider to find the flash frame."),
        tags$li("Draw an ROI (drag) on the first cropped frame and click 'Capture ROI' to compute the TIC."),
      ),
      plotOutput("frame_plot", brush = brushOpts(id = "plot_brush", resetOnNew = TRUE), height = "600px"),
      hr(),
      tableOutput("tic_table")
    )
  )
)

server <- function(input, output, session) {
  # Ensure Python packages are available by attempting import
  # Only pydicom and numpy are mandatory; Pillow/pylibjpeg are optional (for display/decoding)
  ensure_py <- function() {
    required <- c("pydicom", "numpy")
    optional <- c("Pillow", "pylibjpeg", "pylibjpeg-libjpeg")
    
    # Check required packages
    for (p in required) {
      ok <- tryCatch({ import(p); TRUE }, error = function(e) FALSE)
      if (!ok) {
        showNotification(paste("Required Python package not available:", p), type = "error")
        return(FALSE)
      }
    }
    
    # Try optional packages but don't fail if missing
    for (p in optional) {
      ok <- tryCatch({ import(p); TRUE }, error = function(e) FALSE)
      if (!ok) {
        message("Optional Python package not found:", p, "— JPEG decoding may fail but raw DICOM reading will work")
      }
    }
    
    return(TRUE)
  }

  rv <- reactiveValues(
    raw = NULL, # raw frames as R array: frames x height x width x (channels optional)
    frames = NULL, # cropped frames array
    crop = NULL, # c(x0,y0,x1,y1)
    roi = NULL, # c(x0,y0,x1,y1)
    playing = FALSE,
    timer = NULL
  )

  observeEvent(input$load_btn, {
    if (!ensure_py()) return()
    # use reticulate to read dicom
    tryCatch({
      pydicom <- import("pydicom")
      np <- import("numpy")
    }, error = function(e) {
      showNotification(paste("Python import failed:", conditionMessage(e)), type = "error"); return()
    })

    path <- input$dicom_path
    # If path is directory, pick the first file
    if (dir.exists(path)) {
      files <- list.files(path, full.names = TRUE)
      if (length(files) == 0) { showNotification("No files in directory"); return() }
      path_use <- files[1]
    } else if (file.exists(path)) {
      path_use <- path
    } else {
      showNotification("Path does not exist", type = "error"); return()
    }

    ds <- tryCatch(pydicom$dcmread(path_use, force = TRUE), error = function(e) { showNotification(paste("pydicom read error:", conditionMessage(e)), type = "error"); return(NULL) })
    if (is.null(ds)) return()

    # obtain pixel_array via reticulate
    if (!py_has_attr(ds, "pixel_array")) {
      showNotification("DICOM has no accessible pixel_array. It may be encapsulated or multi-frame; try using the decompressed file.", type = "error"); return()
    }
    pix <- tryCatch(py_to_r(ds$pixel_array), error = function(e) { showNotification(paste("Failed to get pixel_array:", conditionMessage(e)), type = "error"); return(NULL) })
    if (is.null(pix)) return()

    # Normalize shape: We want a 3D array frames x height x width (grayscale) or frames x h x w x 3 (color)
    # Common pydicom shapes: (frames, rows, cols) or (rows, cols) or (rows, cols, samples)
    dims <- dim(pix)
    if (is.null(dims)) { showNotification("pixel_array has no dims"); return() }

    # Convert to numeric and scale to 0..1 for display
    to_numeric <- function(x) {
      x <- as.numeric(x)
      x
    }

    if (length(dims) == 2) {
      # single frame grayscale
      frames_r <- array(to_numeric(pix), dim = c(1, dims[1], dims[2]))
    } else if (length(dims) == 3) {
      # could be (frames, rows, cols) or (rows, cols, channels)
      if (dims[1] > 1 && dims[3] <= 4) {
        # assume frames x rows x cols
        frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
      } else if (dims[3] <= 4 && dims[1] > 1 && dims[2] > 1) {
        frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
        # reshape to 1 x rows x cols? fallback
        frames_r <- array(frames_r, dim = c(1, dims[1], dims[2]))
      } else if (dims[3] > 4) {
        # frames x rows x cols
        frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
      } else {
        # default
        frames_r <- array(to_numeric(pix), dim = c(dims[1], dims[2], dims[3]))
      }
    } else if (length(dims) == 4) {
      # frames x rows x cols x channels
      frames_r <- array(to_numeric(pix), dim = dims)
    } else {
      showNotification(paste("Unhandled pixel_array dims:", paste(dims, collapse = ",")), type = "error"); return()
    }

    # store raw frames
    rv$raw <- frames_r
    rv$frames <- frames_r
    rv$crop <- NULL
    rv$roi <- NULL

    # configure slider
    nframes <- dim(rv$frames)[1]
    updateSliderInput(session, "frame_slider", min = 1, max = nframes, value = 1)
    showNotification(paste("Loaded frames:", nframes))
  })

  observeEvent(input$apply_crop, {
    if (is.null(rv$raw)) { showNotification("Load a DICOM first", type = "error"); return() }
    b <- input$plot_brush
    if (is.null(b)) { showNotification("Use the mouse to draw a rectangle on the image first (brush)", type = "error"); return() }
    # brush gives xmin,xmax,ymin,ymax in data coords; we plotted with x 0..cols, y 0..rows
    x0 <- floor(max(1, b$xmin))
    x1 <- ceiling(min(dim(rv$raw)[3], b$xmax))
    # note: image origin mapping (y) - brush y corresponds to pixel row index; use floor/ceil
    y0 <- floor(max(1, b$ymin))
    y1 <- ceiling(min(dim(rv$raw)[2], b$ymax))
    rv$crop <- c(x0, y0, x1, y1)
    # apply crop to all frames
    frames <- rv$raw
    # support frames x h x w and frames x h x w x c
    d <- dim(frames)
    if (length(d) == 3) {
      cropped <- frames[, y0:y1, x0:x1, drop = FALSE]
    } else if (length(d) == 4) {
      cropped <- frames[, y0:y1, x0:x1, , drop = FALSE]
    } else {
      showNotification("Unexpected frames array shape", type = "error"); return()
    }
    rv$frames <- cropped
    updateSliderInput(session, "frame_slider", min = 1, max = dim(rv$frames)[1], value = 1)
    showNotification(paste("Applied crop:", paste(rv$crop, collapse = ",")))
  })

  observeEvent(input$reset_crop, {
    if (!is.null(rv$raw)) {
      rv$frames <- rv$raw
      rv$crop <- NULL
      updateSliderInput(session, "frame_slider", min = 1, max = dim(rv$frames)[1], value = 1)
      showNotification("Crop reset")
    }
  })

  # Play control
  observeEvent(input$play_btn, {
    rv$playing <- !rv$playing
    if (rv$playing) {
      updateActionButton(session, "play_btn", label = "Pause")
      rv$timer <- reactiveTimer(100)
    } else {
      updateActionButton(session, "play_btn", label = "Play")
      rv$timer <- NULL
    }
  })

  observe({
    if (!is.null(rv$timer) && rv$playing) {
      rv$timer()
      isolate({
        n <- dim(rv$frames)[1]
        cur <- input$frame_slider
        nx <- ifelse(is.null(cur), 1, cur)
        nx <- nx + 1
        if (nx > n) nx <- 1
        updateSliderInput(session, "frame_slider", value = nx)
      })
    }
  })

  # Capture ROI
  observeEvent(input$capture_roi, {
    if (is.null(rv$frames)) { showNotification("No frames loaded", type = "error"); return() }
    b <- input$plot_brush
    if (is.null(b)) { showNotification("Use the brush to mark the ROI on the displayed frame", type = "error"); return() }
    x0 <- floor(max(1, b$xmin)); x1 <- ceiling(min(dim(rv$frames)[3], b$xmax))
    y0 <- floor(max(1, b$ymin)); y1 <- ceiling(min(dim(rv$frames)[2], b$ymax))
    rv$roi <- c(x0, y0, x1, y1)
    # compute TIC: mean intensity over ROI for each frame
    frames <- rv$frames
    d <- dim(frames)
    n <- d[1]
    tic <- numeric(n)
    for (i in seq_len(n)) {
      frame <- frames[i, , , drop = FALSE]
      # if 3D (h x w x c) handle channels
      if (length(dim(frame)) == 3 && dim(frame)[3] >= 3) {
        # convert to grayscale by luminance approximation
        fr <- frame[,,1]*0.299 + frame[,,2]*0.587 + frame[,,3]*0.114
      } else {
        fr <- matrix(as.numeric(frame), nrow = dim(frame)[2], ncol = dim(frame)[3])
      }
      sub <- fr[y0:y1, x0:x1]
      tic[i] <- mean(sub, na.rm = TRUE)
    }
    times <- seq_len(n)
    df <- data.frame(frame = times, intensity = tic)
    output$tic_table <- renderTable(df)
    rv$tic_df <- df
    showNotification("ROI captured and TIC computed")
  })

  observeEvent(input$clear_roi, {
    rv$roi <- NULL
    rv$tic_df <- NULL
    output$tic_table <- renderTable(NULL)
    showNotification("ROI cleared")
  })

  output$frame_plot <- renderPlot({
    if (is.null(rv$frames)) {
      plot.new(); text(0.5,0.5, "Load a DICOM to begin")
      return()
    }
    idx <- input$frame_slider
    if (is.null(idx)) idx <- 1
    frame <- rv$frames[idx, , , drop = FALSE]
    # if color (h x w x c) or grayscale (h x w)
    if (length(dim(frame)) == 3 && dim(frame)[3] >= 3) {
      img <- frame
      # ensure values in 0..1
      img <- img - min(img, na.rm = TRUE)
      mx <- max(img, na.rm = TRUE); if (mx>0) img <- img/mx
      # rasterImage expects array as (w,h,channels) in R? use as.raster
      h <- dim(img)[1]; w <- dim(img)[2]
      plot(0, type = "n", xlim = c(1, w), ylim = c(1, h), xaxs = "i", yaxs = "i", xaxt = 'n', yaxt = 'n', ylab = '', xlab = '')
      rasterImage(as.raster(img), 1, 1, w, h)
    } else {
      mat <- if (length(dim(frame)) == 3) matrix(frame[,,1], nrow = dim(frame)[2], ncol = dim(frame)[3]) else matrix(frame, nrow = dim(frame)[2], ncol = dim(frame)[3])
      # ensure orientation: image plotting in R has origin bottom-left, so use rasterImage
      h <- nrow(mat); w <- ncol(mat)
      mat2 <- mat
      mat2 <- mat2 - min(mat2, na.rm = TRUE); mx <- max(mat2, na.rm = TRUE); if (mx>0) mat2 <- mat2/mx
      colimg <- gray(1 - mat2)
      plot(0, type = "n", xlim = c(1, w), ylim = c(1, h), xaxs = "i", yaxs = "i", xaxt = 'n', yaxt = 'n', ylab = '', xlab = '')
      rasterImage(as.raster(matrix(colimg, nrow = h, ncol = w)), 1, 1, w, h)
    }
    # overlay crop rectangle
    if (!is.null(rv$crop)) {
      rect(rv$crop[1], rv$crop[2], rv$crop[3], rv$crop[4], border = "green", lwd = 2)
    }
    if (!is.null(rv$roi)) {
      rect(rv$roi[1], rv$roi[2], rv$roi[3], rv$roi[4], border = "red", lwd = 2)
    }
  })

  output$download_tic <- downloadHandler(
    filename = function() { paste0("TIC_", Sys.Date(), ".csv") },
    content = function(file) {
      if (is.null(rv$tic_df)) stop("No TIC computed yet")
      write.csv(rv$tic_df, file, row.names = FALSE)
    }
  )

}

shinyApp(ui, server)
