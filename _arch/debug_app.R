#!/usr/bin/env Rscript
# Simplified Shiny app with extensive debugging

library(shiny)
library(reticulate)

ui <- fluidPage(
  titlePanel("DICOM Test - Debug Version"),
  sidebarLayout(
    sidebarPanel(
      textInput("dicom_path", "DICOM file", value = "data/dicom_file"),
      actionButton("load_btn", "Load DICOM"),
      hr(),
      actionButton("apply_crop", "Apply crop from brush"),
      hr(),
      actionButton("capture_roi", "Capture ROI from brush"),
      hr(),
      downloadButton("download_tic", "Download TIC CSV"),
      hr(),
      verbatimTextOutput("debug_info")
    ),
    mainPanel(
      plotOutput("frame_plot", brush = brushOpts(id = "plot_brush")),
      hr(),
      h4("Debug Log:"),
      verbatimTextOutput("debug_log"),
      hr(),
      tableOutput("tic_table")
    )
  )
)

server <- function(input, output, session) {
  rv <- reactiveValues(
    raw = NULL,
    frames = NULL,
    crop = NULL,
    roi = NULL,
    tic_df = NULL,
    debug_msgs = ""
  )
  
  debug_msg <- function(msg) {
    cat("[DEBUG]", msg, "\n")
    rv$debug_msgs <- paste(rv$debug_msgs, msg, "\n")
  }
  
  ensure_py <- function() {
    tryCatch({
      import("pydicom")
      import("numpy")
      debug_msg("Python packages OK")
      return(TRUE)
    }, error = function(e) {
      debug_msg(paste("Python error:", conditionMessage(e)))
      return(FALSE)
    })
  }
  
  observeEvent(input$load_btn, {
    debug_msg("=== LOAD DICOM START ===")
    if (!ensure_py()) return()
    
    tryCatch({
      pydicom <- import("pydicom")
      path <- input$dicom_path
      debug_msg(paste("Loading from:", path))
      
      ds <- pydicom$dcmread(path, force = TRUE)
      debug_msg("DICOM loaded")
      
      pix <- py_to_r(ds$pixel_array)
      dims <- dim(pix)
      debug_msg(paste("pixel_array shape:", paste(dims, collapse = " x ")))
      
      # Normalize shape
      to_numeric <- function(x) as.numeric(x)
      if (length(dims) == 4) {
        frames_r <- array(to_numeric(pix), dim = dims)
        debug_msg(paste("4D array detected, shape:", paste(dim(frames_r), collapse = " x ")))
      } else if (length(dims) == 3) {
        frames_r <- array(to_numeric(pix), dim = c(1, dims[1], dims[2]))
        debug_msg(paste("3D array detected, reshaped to:", paste(dim(frames_r), collapse = " x ")))
      } else if (length(dims) == 2) {
        frames_r <- array(to_numeric(pix), dim = c(1, dims[1], dims[2]))
        debug_msg(paste("2D array detected, reshaped to:", paste(dim(frames_r), collapse = " x ")))
      }
      
      rv$raw <- frames_r
      rv$frames <- frames_r
      debug_msg(paste("Stored frames, shape:", paste(dim(rv$frames), collapse = " x ")))
      
      nframes <- dim(rv$frames)[1]
      updateSliderInput(session, "frame_slider", min = 1, max = nframes, value = 1)
      debug_msg(paste("Slider updated: 1 -", nframes))
      debug_msg("=== LOAD DICOM SUCCESS ===")
      
    }, error = function(e) {
      debug_msg(paste("ERROR:", conditionMessage(e)))
      debug_msg(paste("Traceback:", paste(e$traceback, collapse = "\n")))
    })
  })
  
  observeEvent(input$apply_crop, {
    debug_msg("=== CROP START ===")
    if (is.null(rv$raw)) {
      debug_msg("ERROR: No raw frames")
      return()
    }
    b <- input$plot_brush
    if (is.null(b)) {
      debug_msg("ERROR: No brush")
      return()
    }
    
    tryCatch({
      x0 <- floor(max(1, b$xmin))
      x1 <- ceiling(min(dim(rv$raw)[3], b$xmax))
      y0 <- floor(max(1, b$ymin))
      y1 <- ceiling(min(dim(rv$raw)[2], b$ymax))
      debug_msg(paste("Crop region: x[", x0, ":", x1, "] y[", y0, ":", y1, "]"))
      
      rv$crop <- c(x0, y0, x1, y1)
      frames <- rv$raw
      d <- dim(frames)
      debug_msg(paste("frames shape:", paste(d, collapse = " x ")))
      
      if (length(d) == 4) {
        cropped <- frames[, y0:y1, x0:x1, , drop = FALSE]
        debug_msg(paste("Cropped using 4D indexing"))
      } else if (length(d) == 3) {
        cropped <- frames[, y0:y1, x0:x1, drop = FALSE]
        debug_msg(paste("Cropped using 3D indexing"))
      }
      
      debug_msg(paste("Cropped shape:", paste(dim(cropped), collapse = " x ")))
      rv$frames <- cropped
      debug_msg("=== CROP SUCCESS ===")
    }, error = function(e) {
      debug_msg(paste("CROP ERROR:", conditionMessage(e)))
    })
  })
  
  observeEvent(input$capture_roi, {
    debug_msg("=== ROI START ===")
    if (is.null(rv$frames)) {
      debug_msg("ERROR: No frames")
      return()
    }
    b <- input$plot_brush
    if (is.null(b)) {
      debug_msg("ERROR: No brush for ROI")
      return()
    }
    
    tryCatch({
      x0 <- floor(max(1, b$xmin))
      x1 <- ceiling(min(dim(rv$frames)[3], b$xmax))
      y0 <- floor(max(1, b$ymin))
      y1 <- ceiling(min(dim(rv$frames)[2], b$ymax))
      rv$roi <- c(x0, y0, x1, y1)
      debug_msg(paste("ROI region: x[", x0, ":", x1, "] y[", y0, ":", y1, "]"))
      
      frames <- rv$frames
      d <- dim(frames)
      n <- d[1]
      debug_msg(paste("Computing TIC for", n, "frames"))
      
      tic <- numeric(n)
      for (i in seq_len(n)) {
        if (length(d) == 4) {
          frame_3d <- frames[i, , , ]
          frame_2d <- frame_3d[,,1]*0.299 + frame_3d[,,2]*0.587 + frame_3d[,,3]*0.114
        } else {
          frame_2d <- frames[i, , ]
        }
        sub <- frame_2d[y0:y1, x0:x1]
        tic[i] <- mean(sub, na.rm = TRUE)
      }
      
      times <- seq_len(n)
      df <- data.frame(frame = times, intensity = tic)
      rv$tic_df <- df
      debug_msg(paste("TIC computed, rows:", nrow(df)))
      debug_msg("=== ROI SUCCESS ===")
    }, error = function(e) {
      debug_msg(paste("ROI ERROR:", conditionMessage(e)))
    })
  })
  
  output$frame_plot <- renderPlot({
    debug_msg("Rendering frame plot")
    
    if (is.null(rv$frames)) {
      plot.new()
      text(0.5, 0.5, "Load DICOM first")
      return()
    }
    
    tryCatch({
      idx <- input$frame_slider
      if (is.null(idx)) idx <- 1
      
      d <- dim(rv$frames)
      debug_msg(paste("[RENDER] frames shape:", paste(d, collapse = " x ")))
      
      if (length(d) == 4) {
        frame <- rv$frames[idx, , , ]
        debug_msg(paste("[RENDER] extracted 4D frame shape:", paste(dim(frame), collapse = " x ")))
      } else if (length(d) == 3) {
        frame <- rv$frames[idx, , ]
        debug_msg(paste("[RENDER] extracted 3D frame shape:", paste(dim(frame), collapse = " x ")))
      }
      
      if (length(dim(frame)) == 3 && dim(frame)[3] >= 3) {
        debug_msg("[RENDER] RGB image detected")
        img <- frame
        img <- img - min(img, na.rm = TRUE)
        mx <- max(img, na.rm = TRUE)
        if (mx > 0) img <- img / mx
        h <- dim(img)[1]
        w <- dim(img)[2]
        plot(0, type = "n", xlim = c(1, w), ylim = c(1, h), xaxs = "i", yaxs = "i", xaxt = 'n', yaxt = 'n')
        raster_img <- as.raster(array(c(img[,,1], img[,,2], img[,,3]), dim = c(h, w, 3)))
        rasterImage(raster_img, 1, 1, w, h)
        debug_msg("[RENDER] RGB image displayed OK")
      }
    }, error = function(e) {
      debug_msg(paste("[RENDER] ERROR:", conditionMessage(e)))
      plot.new()
      text(0.5, 0.5, paste("Render error:", conditionMessage(e)))
    })
  })
  
  output$debug_log <- renderText({
    rv$debug_msgs
  })
  
  output$debug_info <- renderText({
    if (is.null(rv$frames)) {
      "No frames loaded"
    } else {
      paste("Frames shape:", paste(dim(rv$frames), collapse = " x "))
    }
  })
  
  output$tic_table <- renderTable({
    rv$tic_df
  })
  
  output$download_tic <- downloadHandler(
    filename = function() paste0("TIC_", Sys.Date(), ".csv"),
    content = function(file) {
      if (is.null(rv$tic_df)) stop("No TIC computed")
      write.csv(rv$tic_df, file, row.names = FALSE)
    }
  )
}

shinyApp(ui, server)
