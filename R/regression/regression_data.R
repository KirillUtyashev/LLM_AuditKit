REGRESSION_READY_REQUIRED_COLUMNS <- c(
  "source_file",
  "audit_id",
  "scenario_id",
  "persona_id",
  "model_config_id",
  "candidate_id",
  "candidate_index",
  "candidate_count",
  "city",
  "year",
  "pick",
  "log_probability",
  "pick_top",
  "pick_threshold",
  "preparation_top_share",
  "preparation_probability_threshold",
  "preparation_ranking_group_variables",
  "preparation_scenario_covariates",
  "preparation_candidate_covariates"
)

REGRESSION_LONG_KEY_COLUMNS <- c(
  "scenario_id",
  "persona_id",
  "model_config_id",
  "candidate_id"
)

REGRESSION_PREPARATION_PROVENANCE_COLUMNS <- c(
  "preparation_top_share",
  "preparation_probability_threshold",
  "preparation_ranking_group_variables",
  "preparation_scenario_covariates",
  "preparation_candidate_covariates"
)

.regression_data_abort <- function(source_file, format, ...) {
  stop(
    sprintf(
      "Invalid regression-ready CSV '%s': %s",
      source_file,
      sprintf(format, ...)
    ),
    call. = FALSE
  )
}

.regression_strict_read <- function(path, source_file) {
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
      .regression_data_abort(
        source_file,
        "CSV structure could not be read: %s",
        conditionMessage(error)
      )
    }
  )
  record_counts <- field_counts[!is.na(field_counts)]
  if (length(record_counts) < 2L) {
    .regression_data_abort(
      source_file,
      "CSV must contain a header and at least one data row."
    )
  }
  if (any(record_counts != record_counts[[1L]])) {
    .regression_data_abort(
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
      .regression_data_abort(
        source_file,
        "CSV could not be parsed: %s",
        conditionMessage(error)
      )
    }
  )

  headers <- as.character(parsed[1L, , drop = TRUE])
  headers[[1L]] <- sub("^\ufeff", "", headers[[1L]])
  if (any(!nzchar(trimws(headers)))) {
    .regression_data_abort(source_file, "CSV contains an empty header.")
  }
  duplicate <- duplicated(headers)
  if (any(duplicate)) {
    .regression_data_abort(
      source_file,
      "CSV contains duplicate header '%s'.",
      headers[which(duplicate)[[1L]]]
    )
  }

  data <- parsed[-1L, , drop = FALSE]
  names(data) <- headers
  row.names(data) <- NULL
  data
}

.regression_parse_numeric <- function(
  values,
  field,
  source_file,
  allow_missing = FALSE
) {
  present <- !is.na(values) & nzchar(trimws(values))
  if (!allow_missing && any(!present)) {
    .regression_data_abort(
      source_file,
      "column '%s' contains an empty value at data row %d.",
      field,
      which(!present)[[1L]]
    )
  }
  parsed <- rep(NA_real_, length(values))
  parsed[present] <- suppressWarnings(as.numeric(values[present]))
  invalid <- present & (is.na(parsed) | !is.finite(parsed))
  if (any(invalid)) {
    .regression_data_abort(
      source_file,
      "column '%s' contains invalid numeric value '%s' at data row %d.",
      field,
      values[which(invalid)[[1L]]],
      which(invalid)[[1L]]
    )
  }
  parsed
}

.regression_parse_integer <- function(
  values,
  field,
  source_file,
  positive = FALSE,
  binary = FALSE
) {
  parsed <- .regression_parse_numeric(values, field, source_file)
  invalid <- parsed != trunc(parsed) |
    parsed < -.Machine$integer.max |
    parsed > .Machine$integer.max
  if (positive) {
    invalid <- invalid | parsed <= 0
  }
  if (binary) {
    invalid <- invalid | !(parsed %in% c(0, 1))
  }
  if (any(invalid)) {
    expectation <- if (binary) {
      "binary integers 0 or 1"
    } else if (positive) {
      "positive integers"
    } else {
      "integers"
    }
    .regression_data_abort(
      source_file,
      "column '%s' must contain %s; invalid value '%s' at data row %d.",
      field,
      expectation,
      values[which(invalid)[[1L]]],
      which(invalid)[[1L]]
    )
  }
  as.integer(parsed)
}

.regression_validate_preparation_provenance <- function(raw, source_file) {
  top_share <- .regression_parse_numeric(
    raw$preparation_top_share,
    "preparation_top_share",
    source_file
  )
  probability_threshold <- .regression_parse_numeric(
    raw$preparation_probability_threshold,
    "preparation_probability_threshold",
    source_file
  )
  if (any(top_share <= 0 | top_share > 1)) {
    .regression_data_abort(
      source_file,
      "'preparation_top_share' must be in (0, 1]."
    )
  }
  if (any(probability_threshold <= 0 | probability_threshold > 1)) {
    .regression_data_abort(
      source_file,
      "'preparation_probability_threshold' must be in (0, 1]."
    )
  }
  if (length(unique(top_share)) != 1L) {
    .regression_data_abort(
      source_file,
      "'preparation_top_share' mixes multiple preparation settings."
    )
  }
  if (length(unique(probability_threshold)) != 1L) {
    .regression_data_abort(
      source_file,
      "'preparation_probability_threshold' mixes multiple preparation settings."
    )
  }

  textual <- c(
    "preparation_ranking_group_variables",
    "preparation_scenario_covariates",
    "preparation_candidate_covariates"
  )
  for (field in textual) {
    if (length(unique(raw[[field]])) != 1L) {
      .regression_data_abort(
        source_file,
        "column '%s' mixes multiple preparation settings.",
        field
      )
    }
  }
  ranking <- raw$preparation_ranking_group_variables[[1L]]
  if (is.na(ranking) || !nzchar(trimws(ranking))) {
    .regression_data_abort(
      source_file,
      "'preparation_ranking_group_variables' must not be empty."
    )
  }

  list(
    preparation_top_share = unname(top_share[[1L]]),
    preparation_probability_threshold = unname(
      probability_threshold[[1L]]
    ),
    preparation_ranking_group_variables = ranking,
    preparation_scenario_covariates =
      raw$preparation_scenario_covariates[[1L]],
    preparation_candidate_covariates =
      raw$preparation_candidate_covariates[[1L]]
  )
}

.regression_type_convert <- function(raw) {
  protected_strings <- c(
    "source_file",
    "audit_id",
    REGRESSION_LONG_KEY_COLUMNS,
    "city",
    "preparation_ranking_group_variables",
    "preparation_scenario_covariates",
    "preparation_candidate_covariates"
  )
  converted <- raw
  for (field in names(raw)) {
    if (field %in% protected_strings) {
      next
    }
    converted[[field]] <- type.convert(
      raw[[field]],
      na.strings = "",
      as.is = TRUE
    )
  }
  converted
}

.regression_validate_model_columns <- function(data, config, source_file) {
  configured <- unique(c(
    config$outcome_variable,
    config$explanatory_variables,
    config$control_variables,
    config$fixed_effects,
    config$cluster_variables,
    config$estimation_group_variables
  ))
  missing <- setdiff(configured, names(data))
  if (length(missing) > 0L) {
    .regression_data_abort(
      source_file,
      "missing configured column(s): %s",
      paste(missing, collapse = ", ")
    )
  }

  numerical <- c(
    config$outcome_variable,
    config$explanatory_variables,
    config$control_variables
  )
  for (field in numerical) {
    values <- data[[field]]
    if (is.logical(values)) {
      data[[field]] <- as.integer(values)
      next
    }
    if (!is.numeric(values)) {
      .regression_data_abort(
        source_file,
        "model column '%s' must be numeric or logical.",
        field
      )
    }
    invalid <- !is.na(values) & !is.finite(values)
    if (any(invalid)) {
      .regression_data_abort(
        source_file,
        "model column '%s' contains a non-finite value at data row %d.",
        field,
        which(invalid)[[1L]]
      )
    }
  }

  for (field in unique(c(config$fixed_effects, config$cluster_variables))) {
    values <- data[[field]]
    invalid <- is.numeric(values) & !is.na(values) & !is.finite(values)
    if (any(invalid)) {
      .regression_data_abort(
        source_file,
        "fixed-effect or cluster column '%s' contains a non-finite value at data row %d.",
        field,
        which(invalid)[[1L]]
      )
    }
  }

  for (field in config$estimation_group_variables) {
    values <- data[[field]]
    missing_value <- is.na(values)
    if (is.character(values)) {
      missing_value <- missing_value | !nzchar(trimws(values))
    }
    if (is.numeric(values)) {
      missing_value <- missing_value | !is.finite(values)
    }
    if (any(missing_value)) {
      .regression_data_abort(
        source_file,
        "estimation-group column '%s' is empty or non-finite at data row %d.",
        field,
        which(missing_value)[[1L]]
      )
    }
  }
  data
}

load_regression_data <- function(config) {
  config <- .regression_as_config(config)
  source_file <- config$data_path
  raw <- .regression_strict_read(config$resolved_data_path, source_file)

  missing_required <- setdiff(
    REGRESSION_READY_REQUIRED_COLUMNS,
    names(raw)
  )
  if (length(missing_required) > 0L) {
    .regression_data_abort(
      source_file,
      "missing required regression-ready column(s): %s",
      paste(missing_required, collapse = ", ")
    )
  }

  required_strings <- c(
    "source_file",
    "audit_id",
    REGRESSION_LONG_KEY_COLUMNS,
    "city"
  )
  for (field in required_strings) {
    blank <- is.na(raw[[field]]) | !nzchar(trimws(raw[[field]]))
    if (any(blank)) {
      .regression_data_abort(
        source_file,
        "column '%s' is empty at data row %d.",
        field,
        which(blank)[[1L]]
      )
    }
  }

  if (length(unique(raw$audit_id)) != 1L) {
    .regression_data_abort(
      source_file,
      "column 'audit_id' must contain one audit identity; estimate separate audits separately."
    )
  }

  duplicate_identity <- duplicated(raw[REGRESSION_LONG_KEY_COLUMNS]) |
    duplicated(raw[REGRESSION_LONG_KEY_COLUMNS], fromLast = TRUE)
  if (any(duplicate_identity)) {
    .regression_data_abort(
      source_file,
      "duplicate stable candidate identity at data row %d.",
      which(duplicate_identity)[[1L]]
    )
  }

  provenance <- .regression_validate_preparation_provenance(raw, source_file)
  data <- .regression_type_convert(raw)
  data$candidate_index <- .regression_parse_integer(
    raw$candidate_index,
    "candidate_index",
    source_file,
    positive = TRUE
  )
  data$candidate_count <- .regression_parse_integer(
    raw$candidate_count,
    "candidate_count",
    source_file,
    positive = TRUE
  )
  data$year <- .regression_parse_integer(raw$year, "year", source_file)
  for (field in c("pick", "pick_top", "pick_threshold")) {
    data[[field]] <- .regression_parse_integer(
      raw[[field]],
      field,
      source_file,
      binary = TRUE
    )
  }
  data$log_probability <- .regression_parse_numeric(
    raw$log_probability,
    "log_probability",
    source_file,
    allow_missing = TRUE
  )
  data$preparation_top_share <- rep(
    provenance$preparation_top_share,
    nrow(data)
  )
  data$preparation_probability_threshold <- rep(
    provenance$preparation_probability_threshold,
    nrow(data)
  )

  invalid_index <- data$candidate_index > data$candidate_count
  if (any(invalid_index)) {
    .regression_data_abort(
      source_file,
      "candidate_index exceeds candidate_count at data row %d.",
      which(invalid_index)[[1L]]
    )
  }
  invalid_log_probability <- !is.na(data$log_probability) &
    data$log_probability > 0
  if (any(invalid_log_probability)) {
    .regression_data_abort(
      source_file,
      "log_probability must be at most zero at data row %d.",
      which(invalid_log_probability)[[1L]]
    )
  }
  missing_positive_probability <- data$pick == 1L &
    is.na(data$log_probability)
  if (any(missing_positive_probability)) {
    .regression_data_abort(
      source_file,
      "raw-positive row is missing log_probability at data row %d.",
      which(missing_positive_probability)[[1L]]
    )
  }
  if (any(data$pick_top > data$pick)) {
    .regression_data_abort(
      source_file,
      "pick_top must be a subset of pick."
    )
  }
  expected_threshold <- as.integer(
    data$pick == 1L &
      data$log_probability >= log(provenance$preparation_probability_threshold)
  )
  if (!identical(data$pick_threshold, expected_threshold)) {
    .regression_data_abort(
      source_file,
      "pick_threshold is inconsistent with preparation provenance."
    )
  }

  data <- .regression_validate_model_columns(data, config, source_file)
  stable_order <- do.call(
    order,
    c(unname(data[REGRESSION_LONG_KEY_COLUMNS]), list(method = "radix"))
  )
  data <- data[stable_order, , drop = FALSE]
  row.names(data) <- NULL
  attr(data, "preparation_provenance") <- provenance
  data
}
