PREPARATION_REQUIRED_CANDIDATE_FIELDS <- c(
  "id",
  "pick",
  "log_probability"
)

PREPARATION_LONG_KEY_COLUMNS <- c(
  "scenario_id",
  "persona_id",
  "model_config_id",
  "candidate_id"
)

PREPARATION_OUTPUT_CORE_COLUMNS <- c(
  "source_file",
  "audit_id",
  PREPARATION_LONG_KEY_COLUMNS,
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

.preparation_data_abort <- function(source_file, format, ...) {
  message <- sprintf(format, ...)
  stop(
    sprintf("Invalid candidate data in '%s': %s", source_file, message),
    call. = FALSE
  )
}

.preparation_job_description <- function(data, row) {
  paste(
    sprintf(
      "%s=%s",
      EXPERIMENT_JOB_KEY_COLUMNS,
      unlist(data[row, EXPERIMENT_JOB_KEY_COLUMNS], use.names = FALSE)
    ),
    collapse = ", "
  )
}

.preparation_family_indices <- function(columns, field, source_file) {
  family_pattern <- sprintf("^candidate_([1-9][0-9]*)_%s$", field)
  candidate_pattern <- sprintf("^candidate_[^_]+_%s$", field)
  family_columns <- grep(family_pattern, columns, value = TRUE)
  malformed_columns <- setdiff(
    grep(candidate_pattern, columns, value = TRUE),
    family_columns
  )
  if (length(malformed_columns) > 0L) {
    .preparation_data_abort(
      source_file,
      "candidate family '%s' has invalid column '%s'.",
      field,
      malformed_columns[1L]
    )
  }
  if (length(family_columns) == 0L) {
    .preparation_data_abort(
      source_file,
      "missing candidate family 'candidate_<i>_%s'.",
      field
    )
  }

  index_text <- sub(family_pattern, "\\1", family_columns)
  indices <- suppressWarnings(as.integer(index_text))
  if (any(is.na(indices))) {
    .preparation_data_abort(
      source_file,
      "candidate family '%s' contains an index outside the supported integer range.",
      field
    )
  }
  sort(indices, method = "radix")
}

.preparation_validate_candidate_frame <- function(data, config) {
  source_file <- data$source_file[1L]
  fields <- c(
    PREPARATION_REQUIRED_CANDIDATE_FIELDS,
    config$candidate_covariates
  )
  families <- lapply(
    fields,
    function(field) {
      .preparation_family_indices(names(data), field, source_file)
    }
  )
  names(families) <- fields

  reference_indices <- families[[1L]]
  for (field in fields[-1L]) {
    if (!identical(families[[field]], reference_indices)) {
      .preparation_data_abort(
        source_file,
        "candidate family '%s' does not expose the same indices as family 'id'.",
        field
      )
    }
  }

  candidate_counts <- as.integer(data$candidate_count)
  maximum_candidate_count <- max(candidate_counts)
  contiguous_family <- identical(
    reference_indices,
    seq_along(reference_indices)
  )
  if (
    length(reference_indices) != maximum_candidate_count ||
      !contiguous_family
  ) {
    .preparation_data_abort(
      source_file,
      paste0(
        "candidate families must expose the contiguous indices 1 through ",
        "max(candidate_count)=%d."
      ),
      maximum_candidate_count
    )
  }

  for (candidate_index in reference_indices) {
    active <- candidate_counts >= candidate_index
    id_column <- sprintf("candidate_%d_id", candidate_index)
    blank_id <- active & (
      is.na(data[[id_column]]) |
        !nzchar(trimws(data[[id_column]]))
    )
    if (any(blank_id)) {
      row <- which(blank_id)[1L]
      .preparation_data_abort(
        source_file,
        "candidate %d has an empty stable ID for %s.",
        candidate_index,
        .preparation_job_description(data, row)
      )
    }

    for (field in fields) {
      column <- sprintf("candidate_%d_%s", candidate_index, field)
      populated_above_count <- !active & (
        !is.na(data[[column]]) & nzchar(data[[column]])
      )
      if (any(populated_above_count)) {
        row <- which(populated_above_count)[1L]
        .preparation_data_abort(
          source_file,
          "column '%s' is populated above candidate_count for %s.",
          column,
          .preparation_job_description(data, row)
        )
      }
    }
  }

  invisible(data)
}

.preparation_extract_candidate_field <- function(
  data,
  source_rows,
  candidate_indices,
  field
) {
  values <- rep(NA_character_, length(source_rows))
  for (candidate_index in sort(unique(candidate_indices), method = "radix")) {
    positions <- which(candidate_indices == candidate_index)
    column <- sprintf("candidate_%d_%s", candidate_index, field)
    values[positions] <- data[[column]][source_rows[positions]]
  }
  values
}

.preparation_reshape_candidates <- function(data, config) {
  candidate_counts <- as.integer(data$candidate_count)
  source_rows <- rep.int(seq_len(nrow(data)), candidate_counts)
  candidate_indices <- sequence(candidate_counts)

  long <- data.frame(
    source_file = data$source_file[source_rows],
    scenario_id = data$scenario_id[source_rows],
    persona_id = data$persona_id[source_rows],
    model_config_id = data$model_config_id[source_rows],
    candidate_id = .preparation_extract_candidate_field(
      data,
      source_rows,
      candidate_indices,
      "id"
    ),
    candidate_index = as.integer(candidate_indices),
    candidate_count = candidate_counts[source_rows],
    city = data$city[source_rows],
    year = as.integer(data$year[source_rows]),
    result_status = data$result_status[source_rows],
    raw_pick = .preparation_extract_candidate_field(
      data,
      source_rows,
      candidate_indices,
      "pick"
    ),
    raw_log_probability = .preparation_extract_candidate_field(
      data,
      source_rows,
      candidate_indices,
      "log_probability"
    ),
    check.names = FALSE,
    stringsAsFactors = FALSE
  )

  for (field in config$scenario_covariates) {
    long[[field]] <- data[[field]][source_rows]
  }
  for (field in config$candidate_covariates) {
    long[[field]] <- .preparation_extract_candidate_field(
      data,
      source_rows,
      candidate_indices,
      field
    )
  }
  long
}

.preparation_validate_candidate_identity <- function(long, raw, config) {
  duplicate_long_key <- duplicated(long[PREPARATION_LONG_KEY_COLUMNS]) |
    duplicated(long[PREPARATION_LONG_KEY_COLUMNS], fromLast = TRUE)
  if (any(duplicate_long_key)) {
    row <- which(duplicate_long_key)[1L]
    stop(
      sprintf(
        "Duplicate candidate identity: %s.",
        paste(
          sprintf(
            "%s=%s",
            PREPARATION_LONG_KEY_COLUMNS,
            unlist(long[row, PREPARATION_LONG_KEY_COLUMNS], use.names = FALSE)
          ),
          collapse = ", "
        )
      ),
      call. = FALSE
    )
  }

  scenario_job_counts <- stats::aggregate(
    list(job_count = rep.int(1L, nrow(raw))),
    by = list(scenario_id = raw$scenario_id),
    FUN = sum
  )
  scenario_candidate_counts <- stats::aggregate(
    list(job_count = rep.int(1L, nrow(long))),
    by = long[c("scenario_id", "candidate_id")],
    FUN = sum
  )
  expected_counts <- scenario_job_counts$job_count[
    match(scenario_candidate_counts$scenario_id, scenario_job_counts$scenario_id)
  ]
  inconsistent_set <- scenario_candidate_counts$job_count != expected_counts
  if (any(inconsistent_set)) {
    row <- which(inconsistent_set)[1L]
    stop(
      sprintf(
        paste0(
          "Scenario '%s' has inconsistent candidate-ID sets across ",
          "experiment jobs; candidate '%s' is not present exactly once per job."
        ),
        scenario_candidate_counts$scenario_id[row],
        scenario_candidate_counts$candidate_id[row]
      ),
      call. = FALSE
    )
  }

  for (field in config$candidate_covariates) {
    values <- unique(long[c("scenario_id", "candidate_id", field)])
    pair <- values[c("scenario_id", "candidate_id")]
    conflicting <- duplicated(pair) | duplicated(pair, fromLast = TRUE)
    if (any(conflicting)) {
      row <- which(conflicting)[1L]
      stop(
        sprintf(
          "Scenario '%s' candidate '%s' has inconsistent '%s' values.",
          values$scenario_id[row],
          values$candidate_id[row],
          field
        ),
        call. = FALSE
      )
    }
  }

  invisible(long)
}

.preparation_status_report <- function(raw) {
  statuses <- sort(unique(raw$result_status), method = "radix")
  counts <- vapply(
    statuses,
    function(status) sum(raw$result_status == status),
    integer(1)
  )
  names(counts) <- statuses
  completed_jobs <- unname(counts["completed"])
  if (length(completed_jobs) == 0L || is.na(completed_jobs)) {
    completed_jobs <- 0L
  }
  excluded <- counts[names(counts) != "completed"]
  list(
    total_jobs = nrow(raw),
    completed_jobs = as.integer(completed_jobs),
    excluded_jobs = as.integer(sum(excluded)),
    excluded_by_status = excluded
  )
}

.preparation_validate_completed_values <- function(long) {
  invalid_pick <- !(long$raw_pick %in% c("0", "1"))
  if (any(invalid_pick)) {
    row <- which(invalid_pick)[1L]
    stop(
      sprintf(
        "Completed candidate '%s' has invalid pick '%s'; expected exactly 0 or 1.",
        long$candidate_id[row],
        long$raw_pick[row]
      ),
      call. = FALSE
    )
  }

  pick <- as.integer(long$raw_pick)
  has_log_probability <- !is.na(long$raw_log_probability) &
    nzchar(trimws(long$raw_log_probability))
  missing_positive_probability <- pick == 1L & !has_log_probability
  if (any(missing_positive_probability)) {
    row <- which(missing_positive_probability)[1L]
    stop(
      sprintf(
        "Raw-positive candidate '%s' is missing log_probability.",
        long$candidate_id[row]
      ),
      call. = FALSE
    )
  }

  log_probability <- rep(NA_real_, nrow(long))
  log_probability[has_log_probability] <- suppressWarnings(
    as.numeric(long$raw_log_probability[has_log_probability])
  )
  invalid_probability <- has_log_probability & (
    is.na(log_probability) |
      !is.finite(log_probability) |
      log_probability > 0
  )
  if (any(invalid_probability)) {
    row <- which(invalid_probability)[1L]
    stop(
      sprintf(
        paste0(
          "Completed candidate '%s' has invalid log_probability '%s'; ",
          "expected a finite number at most zero."
        ),
        long$candidate_id[row],
        long$raw_log_probability[row]
      ),
      call. = FALSE
    )
  }

  long$pick <- pick
  long$log_probability <- log_probability
  long
}

.preparation_validate_ranking_values <- function(data, variables) {
  for (field in variables) {
    values <- data[[field]]
    missing <- is.na(values)
    if (is.character(values)) {
      missing <- missing | !nzchar(trimws(values))
    }
    if (any(missing)) {
      stop(
        sprintf(
          "Ranking-group field '%s' is empty for candidate '%s'.",
          field,
          data$candidate_id[which(missing)[1L]]
        ),
        call. = FALSE
      )
    }
  }
  invisible(data)
}

.preparation_group_ids <- function(data, variables) {
  order_arguments <- c(
    unname(data[variables]),
    list(na.last = TRUE, method = "radix")
  )
  ordered_rows <- do.call(order, order_arguments)
  boundaries <- rep(FALSE, max(nrow(data) - 1L, 0L))
  if (length(boundaries) > 0L) {
    for (field in variables) {
      values <- data[[field]][ordered_rows]
      boundaries <- boundaries | values[-1L] != values[-length(values)]
    }
  }
  ordered_group_ids <- cumsum(c(TRUE, boundaries))
  group_ids <- integer(nrow(data))
  group_ids[ordered_rows] <- ordered_group_ids
  group_ids
}

.preparation_top_cutoff <- function(top_share, group_size) {
  unrounded <- top_share * group_size
  nearest_integer <- round(unrounded)
  tolerance <- 8 * .Machine$double.eps * abs(unrounded)
  if (abs(unrounded - nearest_integer) <= tolerance) {
    return(as.integer(nearest_integer))
  }
  as.integer(ceiling(unrounded))
}

.preparation_construct_outcomes <- function(data, config) {
  .preparation_validate_ranking_values(
    data,
    config$ranking_group_variables
  )
  group_ids <- .preparation_group_ids(
    data,
    config$ranking_group_variables
  )
  pick_top <- integer(nrow(data))
  grouped_rows <- split(seq_len(nrow(data)), group_ids)

  for (group_rows in grouped_rows) {
    cutoff <- .preparation_top_cutoff(
      config$top_share,
      length(group_rows)
    )
    eligible_rows <- group_rows[data$pick[group_rows] == 1L]
    if (length(eligible_rows) == 0L) {
      next
    }
    tie_order <- order(
      -data$log_probability[eligible_rows],
      data$scenario_id[eligible_rows],
      data$persona_id[eligible_rows],
      data$model_config_id[eligible_rows],
      data$candidate_id[eligible_rows],
      method = "radix"
    )
    selected <- eligible_rows[tie_order][
      seq_len(min(cutoff, length(eligible_rows)))
    ]
    pick_top[selected] <- 1L
  }

  data$pick_top <- pick_top
  data$pick_threshold <- as.integer(
    data$pick == 1L &
      data$log_probability >= log(config$probability_threshold)
  )
  data
}

.preparation_finalize_output <- function(data, config, report) {
  data$audit_id <- rep(config$audit_id, nrow(data))
  data$preparation_top_share <- rep(config$top_share, nrow(data))
  data$preparation_probability_threshold <- rep(
    config$probability_threshold,
    nrow(data)
  )
  data$preparation_ranking_group_variables <- rep(
    paste(config$ranking_group_variables, collapse = "|"),
    nrow(data)
  )
  data$preparation_scenario_covariates <- rep(
    paste(config$scenario_covariates, collapse = "|"),
    nrow(data)
  )
  data$preparation_candidate_covariates <- rep(
    paste(config$candidate_covariates, collapse = "|"),
    nrow(data)
  )

  output_columns <- c(
    PREPARATION_OUTPUT_CORE_COLUMNS,
    config$scenario_covariates,
    config$candidate_covariates
  )
  output <- data[output_columns]
  output_order <- order(
    output$scenario_id,
    output$persona_id,
    output$model_config_id,
    output$candidate_id,
    method = "radix"
  )
  output <- output[output_order, , drop = FALSE]
  row.names(output) <- NULL
  attr(output, "preparation_report") <- report
  output
}

prepare_regression_data <- function(config) {
  config <- .experiment_results_as_config(config)
  frames <- .experiment_results_load_frames(config)
  for (frame in frames) {
    .preparation_validate_candidate_frame(frame, config)
  }
  raw <- .experiment_results_combine_frames(frames, config)
  report <- .preparation_status_report(raw)
  long <- do.call(
    rbind,
    lapply(frames, .preparation_reshape_candidates, config = config)
  )
  row.names(long) <- NULL
  .preparation_validate_candidate_identity(long, raw, config)

  if (report$completed_jobs == 0L) {
    stop(
      sprintf(
        "No completed experiment jobs remain; excluded %d non-completed job(s).",
        report$excluded_jobs
      ),
      call. = FALSE
    )
  }

  completed <- long$result_status == "completed"
  completed <- long[completed, , drop = FALSE]
  completed <- .preparation_validate_completed_values(completed)
  completed <- .preparation_construct_outcomes(completed, config)
  .preparation_finalize_output(completed, config, report)
}
