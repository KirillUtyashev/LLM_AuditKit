EXPERIMENT_JOB_KEY_COLUMNS <- c(
  "scenario_id",
  "persona_id",
  "model_config_id"
)

EXPERIMENT_RESULT_ENVELOPE_COLUMNS <- c(
  EXPERIMENT_JOB_KEY_COLUMNS,
  "result_status",
  "candidate_count",
  "city",
  "year"
)

.experiment_results_abort <- function(source_file, format, ...) {
  message <- sprintf(format, ...)
  stop(
    sprintf("Invalid experiment-result CSV '%s': %s", source_file, message),
    call. = FALSE
  )
}

.experiment_results_strict_read <- function(path, source_file) {
  field_counts <- tryCatch(
    withCallingHandlers(
      utils::count.fields(
        path,
        sep = ",",
        quote = "\"",
        blank.lines.skip = FALSE,
        comment.char = ""
      ),
      warning = function(warning) {
        stop(simpleError(conditionMessage(warning)))
      }
    ),
    error = function(error) {
      .experiment_results_abort(
        source_file,
        "CSV structure could not be read: %s",
        conditionMessage(error)
      )
    }
  )
  record_counts <- field_counts[!is.na(field_counts)]
  if (length(record_counts) < 2L) {
    .experiment_results_abort(
      source_file,
      "CSV must contain a header and at least one data row."
    )
  }
  if (any(record_counts != record_counts[1L])) {
    .experiment_results_abort(
      source_file,
      "CSV records have inconsistent field counts."
    )
  }

  parsed <- tryCatch(
    withCallingHandlers(
      utils::read.csv(
        path,
        header = FALSE,
        colClasses = "character",
        check.names = FALSE,
        fill = FALSE,
        comment.char = "",
        na.strings = character(),
        blank.lines.skip = FALSE,
        fileEncoding = "UTF-8"
      ),
      warning = function(warning) {
        stop(simpleError(conditionMessage(warning)))
      }
    ),
    error = function(error) {
      .experiment_results_abort(
        source_file,
        "CSV could not be parsed: %s",
        conditionMessage(error)
      )
    }
  )

  headers <- as.character(parsed[1L, , drop = TRUE])
  headers[1L] <- sub("^\ufeff", "", headers[1L])
  if (any(!nzchar(trimws(headers)))) {
    .experiment_results_abort(source_file, "CSV contains an empty header.")
  }
  duplicate_header <- duplicated(headers)
  if (any(duplicate_header)) {
    .experiment_results_abort(
      source_file,
      "CSV contains duplicate header '%s'.",
      headers[which(duplicate_header)[1L]]
    )
  }

  data <- parsed[-1L, , drop = FALSE]
  names(data) <- headers
  row.names(data) <- NULL
  data
}

.experiment_results_validate_nonblank <- function(
  data,
  fields,
  source_file
) {
  for (field in fields) {
    blank <- is.na(data[[field]]) | !nzchar(trimws(data[[field]]))
    if (any(blank)) {
      .experiment_results_abort(
        source_file,
        "column '%s' is empty at source row %d.",
        field,
        which(blank)[1L]
      )
    }
  }
  invisible(data)
}

.experiment_results_validate_frame <- function(data, config, source_file) {
  if ("source_file" %in% names(data)) {
    .experiment_results_abort(
      source_file,
      "input owns reserved column 'source_file'."
    )
  }

  required <- c(
    EXPERIMENT_RESULT_ENVELOPE_COLUMNS,
    config$scenario_covariates
  )
  missing <- setdiff(required, names(data))
  if (length(missing) > 0L) {
    .experiment_results_abort(
      source_file,
      "missing required column(s): %s",
      paste(missing, collapse = ", ")
    )
  }

  for (covariate in config$candidate_covariates) {
    pattern <- sprintf("^candidate_[1-9][0-9]*_%s$", covariate)
    if (!any(grepl(pattern, names(data)))) {
      .experiment_results_abort(
        source_file,
        "missing configured candidate family 'candidate_<i>_%s'.",
        covariate
      )
    }
  }

  .experiment_results_validate_nonblank(
    data,
    EXPERIMENT_RESULT_ENVELOPE_COLUMNS,
    source_file
  )

  valid_candidate_count <- grepl("^[1-9][0-9]*$", data$candidate_count) &
    !is.na(suppressWarnings(as.integer(data$candidate_count)))
  if (any(!valid_candidate_count)) {
    .experiment_results_abort(
      source_file,
      "'candidate_count' must contain positive integers; invalid value '%s' at source row %d.",
      data$candidate_count[which(!valid_candidate_count)[1L]],
      which(!valid_candidate_count)[1L]
    )
  }
  valid_year <- grepl("^[+-]?[0-9]+$", data$year) &
    !is.na(suppressWarnings(as.integer(data$year)))
  if (any(!valid_year)) {
    .experiment_results_abort(
      source_file,
      "'year' must contain integers; invalid value '%s' at source row %d.",
      data$year[which(!valid_year)[1L]],
      which(!valid_year)[1L]
    )
  }

  data
}

.experiment_results_bind <- function(frames) {
  all_columns <- Reduce(
    function(existing, frame) c(existing, setdiff(names(frame), existing)),
    frames,
    init = character()
  )
  aligned <- lapply(
    frames,
    function(frame) {
      missing <- setdiff(all_columns, names(frame))
      for (column in missing) {
        frame[[column]] <- rep(NA_character_, nrow(frame))
      }
      frame[all_columns]
    }
  )
  combined <- do.call(rbind, aligned)
  row.names(combined) <- NULL
  combined
}

.experiment_results_validate_job_keys <- function(data) {
  job_keys <- data[EXPERIMENT_JOB_KEY_COLUMNS]
  duplicate <- duplicated(job_keys) | duplicated(job_keys, fromLast = TRUE)
  if (!any(duplicate)) {
    return(invisible(data))
  }

  offenders <- unique(
    data[duplicate, c("source_file", EXPERIMENT_JOB_KEY_COLUMNS), drop = FALSE]
  )
  offenders <- head(offenders, 5L)
  formatted <- apply(
    offenders,
    1L,
    function(row) {
      sprintf(
        "(%s) in %s",
        paste(
          sprintf("%s=%s", EXPERIMENT_JOB_KEY_COLUMNS, row[EXPERIMENT_JOB_KEY_COLUMNS]),
          collapse = ", "
        ),
        row[["source_file"]]
      )
    }
  )
  stop(
    sprintf(
      "Duplicate ExperimentJobKey value(s): %s",
      paste(formatted, collapse = "; ")
    ),
    call. = FALSE
  )
}

.experiment_results_validate_audit_scope <- function(data, config) {
  for (field in c("persona_id", "model_config_id")) {
    values <- sort(unique(data[[field]]), method = "radix")
    if (length(values) == 1L) {
      next
    }

    value_sources <- vapply(
      values,
      function(value) {
        sources <- unique(data$source_file[data[[field]] == value])
        sprintf(
          "'%s' in %s",
          value,
          paste(sprintf("'%s'", sources), collapse = ", ")
        )
      },
      character(1)
    )
    stop(
      sprintf(
        paste0(
          "Researcher-assigned audit_id '%s' spans multiple %s values ",
          "across its configured experiment-result rows/files: %s. ",
          "Each preparation config/audit_id must contain exactly one %s; ",
          "split different %s values into separate preparation configs ",
          "with different audit_id values."
        ),
        config$audit_id,
        field,
        paste(value_sources, collapse = "; "),
        field,
        field
      ),
      call. = FALSE
    )
  }
  invisible(data)
}

.experiment_results_validate_scenarios <- function(data, scenario_covariates) {
  fields <- c("city", "year", "candidate_count", scenario_covariates)
  for (field in fields) {
    comparison_values <- data[[field]]
    if (field %in% c("year", "candidate_count")) {
      comparison_values <- as.integer(comparison_values)
    }
    pairs <- unique(
      data.frame(
        scenario_id = data$scenario_id,
        comparison_value = comparison_values,
        stringsAsFactors = FALSE
      )
    )
    conflicting <- duplicated(pairs$scenario_id) |
      duplicated(pairs$scenario_id, fromLast = TRUE)
    if (any(conflicting)) {
      scenario_id <- pairs$scenario_id[which(conflicting)[1L]]
      stop(
        sprintf(
          "Scenario '%s' has inconsistent '%s' values across experiment jobs.",
          scenario_id,
          field
        ),
        call. = FALSE
      )
    }
  }
  invisible(data)
}

.experiment_results_as_config <- function(config) {
  if (is.character(config) && length(config) == 1L && !is.na(config)) {
    config <- load_preparation_config(config)
  }
  if (!inherits(config, "preparation_config")) {
    stop(
      "'config' must be a preparation_config or one YAML config path.",
      call. = FALSE
    )
  }
  config
}

.experiment_results_load_frames <- function(config) {
  Map(
    function(path, source_file) {
      data <- .experiment_results_strict_read(path, source_file)
      data <- .experiment_results_validate_frame(data, config, source_file)
      data.frame(
        source_file = rep(source_file, nrow(data)),
        data,
        check.names = FALSE,
        stringsAsFactors = FALSE
      )
    },
    config$resolved_input_paths,
    config$input_paths
  )
}

.experiment_results_combine_frames <- function(frames, config) {
  combined <- .experiment_results_bind(frames)
  .experiment_results_validate_audit_scope(combined, config)
  .experiment_results_validate_job_keys(combined)
  .experiment_results_validate_scenarios(
    combined,
    config$scenario_covariates
  )
  combined
}

load_experiment_results <- function(config) {
  config <- .experiment_results_as_config(config)
  frames <- .experiment_results_load_frames(config)
  .experiment_results_combine_frames(frames, config)
}
