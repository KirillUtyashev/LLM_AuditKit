.regression_parse_cli_args <- function(args) {
  if (
    length(args) != 2L ||
      !identical(args[[1L]], "--config") ||
      !nzchar(trimws(args[[2L]]))
  ) {
    stop(
      "Usage: Rscript scripts/run_regression.R --config <path>",
      call. = FALSE
    )
  }
  args[[2L]]
}

.regression_write_csv_atomic <- function(data, output_path) {
  previous_options <- options(scipen = 0)
  on.exit(options(previous_options), add = TRUE)

  output_directory <- dirname(output_path)
  if (!dir.exists(output_directory)) {
    created <- dir.create(
      output_directory,
      recursive = TRUE,
      showWarnings = FALSE
    )
    if (!isTRUE(created) && !dir.exists(output_directory)) {
      stop(
        sprintf("Could not create output directory: %s", output_directory),
        call. = FALSE
      )
    }
  }
  if (!isTRUE(file.info(output_directory)$isdir)) {
    stop(
      sprintf("Output parent is not a directory: %s", output_directory),
      call. = FALSE
    )
  }
  if (file.access(output_directory, mode = 2L) != 0L) {
    stop(
      sprintf("Output directory is not writable: %s", output_directory),
      call. = FALSE
    )
  }

  temporary_path <- tempfile(
    pattern = paste0(".", basename(output_path), "-"),
    tmpdir = output_directory,
    fileext = ".tmp"
  )
  on.exit(unlink(temporary_path, force = TRUE), add = TRUE)
  tryCatch(
    utils::write.table(
      data,
      file = temporary_path,
      sep = ",",
      row.names = FALSE,
      col.names = TRUE,
      quote = TRUE,
      qmethod = "double",
      na = "",
      eol = "\n",
      fileEncoding = "UTF-8"
    ),
    error = function(error) {
      stop(
        sprintf(
          "Could not write temporary regression-results CSV: %s",
          conditionMessage(error)
        ),
        call. = FALSE
      )
    }
  )
  replaced <- suppressWarnings(file.rename(temporary_path, output_path))
  if (!isTRUE(replaced)) {
    stop(
      paste0(
        "Could not atomically replace regression-results CSV: ",
        output_path,
        ". Any existing artifact was left unchanged."
      ),
      call. = FALSE
    )
  }
  invisible(output_path)
}

run_regressions <- function(config) {
  config <- .regression_as_config(config)
  results <- estimate_regressions(config)
  fit_count <- attr(results, "regression_fit_count", exact = TRUE)
  .regression_write_csv_atomic(results, config$resolved_output_path)
  coefficient_count <- as.integer(nrow(results) / 3L)
  message(
    sprintf(
      paste0(
        "Estimated %d fit(s) and %d coefficient(s); wrote %d result row(s) ",
        "to %s."
      ),
      fit_count,
      coefficient_count,
      nrow(results),
      config$resolved_output_path
    )
  )
  invisible(results)
}
