.preparation_parse_cli_args <- function(args) {
  if (
    length(args) != 2L ||
      !identical(args[[1L]], "--config") ||
      !nzchar(trimws(args[[2L]]))
  ) {
    stop(
      "Usage: Rscript scripts/prepare_regression_data.R --config <path>",
      call. = FALSE
    )
  }
  args[[2L]]
}

.preparation_write_csv_atomic <- function(data, output_path) {
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
          "Could not write temporary regression-ready CSV: %s",
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
        "Could not atomically replace output CSV: ",
        output_path,
        ". Any existing artifact was left unchanged."
      ),
      call. = FALSE
    )
  }
  invisible(output_path)
}

.preparation_report_message <- function(report, candidate_rows) {
  excluded_detail <- if (length(report$excluded_by_status) == 0L) {
    "none"
  } else {
    paste(
      sprintf(
        "%s=%d",
        names(report$excluded_by_status),
        report$excluded_by_status
      ),
      collapse = ", "
    )
  }
  sprintf(
    paste0(
      "Prepared %d candidate row(s) from %d completed job(s); ",
      "excluded %d non-completed job(s) (%s)."
    ),
    candidate_rows,
    report$completed_jobs,
    report$excluded_jobs,
    excluded_detail
  )
}

run_regression_preparation <- function(config) {
  config <- .experiment_results_as_config(config)
  prepared <- prepare_regression_data(config)
  report <- attr(prepared, "preparation_report", exact = TRUE)
  .preparation_write_csv_atomic(prepared, config$resolved_output_path)
  message(.preparation_report_message(report, nrow(prepared)))
  invisible(prepared)
}
