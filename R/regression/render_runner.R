.render_parse_cli_args <- function(args) {
  if (
    length(args) != 2L || !identical(args[[1L]], "--config") ||
      is.na(args[[2L]]) || !nzchar(trimws(args[[2L]]))
  ) {
    stop(
      "Usage: Rscript scripts/render_regression_plot.R --config <path>",
      call. = FALSE
    )
  }
  args[[2L]]
}

.render_write_png_atomic <- function(plot, config) {
  output_path <- config$resolved_output_path
  directory <- dirname(output_path)
  if (!dir.exists(directory)) {
    created <- dir.create(directory, recursive = TRUE, showWarnings = FALSE)
    if (!isTRUE(created) && !dir.exists(directory)) {
      stop(sprintf("Could not create PNG output directory: %s", directory), call. = FALSE)
    }
  }
  if (!isTRUE(file.info(directory)$isdir) || file.access(directory, 2L) != 0L) {
    stop(sprintf("PNG output directory is not writable: %s", directory), call. = FALSE)
  }
  temporary_path <- tempfile(
    pattern = paste0(".", basename(output_path), "-"),
    tmpdir = directory, fileext = ".tmp"
  )
  device <- NULL
  on.exit({
    if (!is.null(device) && device %in% grDevices::dev.list()) {
      suppressWarnings(grDevices::dev.off(device))
    }
    unlink(temporary_path, force = TRUE)
  }, add = TRUE)
  tryCatch(
    withCallingHandlers({
      png_arguments <- list(
        # png() treats filenames as page-number formats; configured paths are
        # literal, including any percent signs in their directories or basename.
        filename = gsub("%", "%%", temporary_path, fixed = TRUE),
        width = as.integer(round(config$width * config$dpi)),
        height = as.integer(round(config$height * config$dpi)),
        units = "px", res = config$dpi, bg = "white"
      )
      # Respect R's platform bitmapType (e.g. native Quartz on macOS).
      # Compiled-in Cairo support does not guarantee its shared libraries exist.
      do.call(grDevices::png, png_arguments)
      device <- grDevices::dev.cur()
      print(plot)
      grDevices::dev.off(device)
      device <- NULL
    }, warning = function(warning) {
      stop(simpleError(conditionMessage(warning)))
    }),
    error = function(error) {
      stop(
        sprintf("Could not render PNG: %s", conditionMessage(error)),
        call. = FALSE
      )
    }
  )
  if (!file.exists(temporary_path) || file.info(temporary_path)$size == 0) {
    stop("Rendering did not create a nonempty PNG artifact.", call. = FALSE)
  }
  if (!isTRUE(suppressWarnings(file.rename(temporary_path, output_path)))) {
    stop(
      paste0("Could not atomically replace PNG: ", output_path,
        ". Any existing artifact was left unchanged."),
      call. = FALSE
    )
  }
  invisible(output_path)
}

render_regression_plot <- function(config) {
  config <- .render_as_config(config)
  prepared <- prepare_regression_plot_data(config)
  plot <- build_regression_plot(prepared)
  .render_write_png_atomic(plot, config)
  message(sprintf(
    "Rendered %d coefficient(s) across %d panel(s) to %s (%d x %d pixels).",
    nrow(prepared$data), length(prepared$panel_order), config$resolved_output_path,
    as.integer(round(config$width * config$dpi)),
    as.integer(round(config$height * config$dpi))
  ))
  invisible(prepared)
}
