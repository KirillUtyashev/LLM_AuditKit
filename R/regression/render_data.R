RENDER_CONFIDENCE_LEVELS <- c(0.90, 0.95, 0.99)

RENDER_GLOBAL_COMPATIBILITY_COLUMNS <- c(
  "term", "estimation_group_variables", "estimator",
  "estimator_version", "inference_contract_id",
  "preparation_top_share", "preparation_probability_threshold",
  "preparation_ranking_group_variables", "preparation_scenario_covariates",
  "preparation_candidate_covariates"
)

RENDER_PANEL_COMPATIBILITY_COLUMNS <- c(
  "audit_id", "dataset_id", "explanatory_variables", "control_variables",
  "fixed_effects",
  "cluster_variables", "vcov_type"
)

.render_data_abort <- function(source, format, ...) {
  stop(
    sprintf("Invalid regression results '%s': %s", source, sprintf(format, ...)),
    call. = FALSE
  )
}

.render_result_column <- function(values, field, source) {
  if (!is.atomic(values) || !is.null(dim(values))) {
    .render_data_abort(
      source, "column '%s' must be one atomic vector, not a list or matrix.", field
    )
  }
  as.character(values)
}

.render_read_csv <- function(path, source) {
  parsed <- tryCatch(
    withCallingHandlers({
      counts <- utils::count.fields(
        path, sep = ",", quote = "\"", comment.char = "",
        blank.lines.skip = FALSE
      )
      counts <- counts[!is.na(counts)]
      if (length(counts) < 2L) {
        stop("CSV must contain a header and at least one data row.")
      }
      if (any(counts != counts[[1L]])) {
        stop("CSV records have inconsistent field counts.")
      }
      utils::read.csv(
        path, header = FALSE, colClasses = "character", check.names = FALSE,
        fill = FALSE, comment.char = "", na.strings = character(),
        blank.lines.skip = FALSE, fileEncoding = "UTF-8"
      )
    }, warning = function(warning) {
      stop(simpleError(conditionMessage(warning)))
    }),
    error = function(error) {
      .render_data_abort(source, "CSV could not be read: %s", conditionMessage(error))
    }
  )
  headers <- as.character(parsed[1L, , drop = TRUE])
  headers[[1L]] <- sub("^\ufeff", "", headers[[1L]])
  if (any(!nzchar(trimws(headers))) || anyDuplicated(headers)) {
    .render_data_abort(source, "CSV headers must be nonempty and distinct.")
  }
  data <- parsed[-1L, , drop = FALSE]
  names(data) <- headers
  row.names(data) <- NULL
  data
}

.render_numeric <- function(values, field, source) {
  values <- .render_result_column(values, field, source)
  parsed <- suppressWarnings(as.numeric(values))
  invalid <- is.na(values) | !nzchar(trimws(values)) |
    is.na(parsed) | !is.finite(parsed)
  if (any(invalid)) {
    .render_data_abort(
      source, "column '%s' must be finite numeric data; invalid data row %d.",
      field, which(invalid)[[1L]]
    )
  }
  parsed
}

.render_metadata_names <- function(value, field, source, allow_empty = TRUE) {
  if (
    length(value) != 1L || is.na(value) || !is.character(value)
  ) {
    .render_data_abort(source, "column '%s' has an invalid ordered name list.", field)
  }
  if (identical(value, "") && allow_empty) {
    return(character())
  }
  values <- strsplit(value, "|", fixed = TRUE)[[1L]]
  if (
    !nzchar(value) || endsWith(value, "|") ||
      any(!grepl("^[A-Za-z][A-Za-z0-9_]*$", values)) ||
      anyDuplicated(values)
  ) {
    .render_data_abort(source, "column '%s' has an invalid ordered name list.", field)
  }
  values
}

.render_validate_cluster_counts <- function(data, source) {
  configurations <- unique(data[c(
    "vcov_type", "cluster_variables", "cluster_counts", "n_used"
  )])
  for (i in seq_len(nrow(configurations))) {
    row <- configurations[i, , drop = FALSE]
    variables <- .render_metadata_names(
      row$cluster_variables, "cluster_variables", source
    )
    if (identical(row$vcov_type, "iid")) {
      if (length(variables) > 0L || nzchar(row$cluster_counts)) {
        .render_data_abort(source, "IID rows must have empty cluster metadata.")
      }
      next
    }
    if (!identical(row$vcov_type, "cluster") || length(variables) == 0L) {
      .render_data_abort(source, "vcov_type and cluster_variables disagree.")
    }
    parts <- strsplit(row$cluster_counts, "|", fixed = TRUE)[[1L]]
    if (
      endsWith(row$cluster_counts, "|") || length(parts) != length(variables) ||
        any(!grepl("^[A-Za-z][A-Za-z0-9_]*=[0-9]+$", parts))
    ) {
      .render_data_abort(source, "cluster_counts must contain ordered name=count entries.")
    }
    count_names <- sub("=.*$", "", parts)
    counts <- suppressWarnings(as.numeric(sub("^[^=]+=", "", parts)))
    if (
      !identical(count_names, variables) || any(!is.finite(counts)) ||
        any(counts < 2 | counts > row$n_used)
    ) {
      .render_data_abort(source, "cluster_counts do not match the used sample or variables.")
    }
  }
}

.render_validate_result_file <- function(raw, source) {
  if (!is.data.frame(raw)) {
    .render_data_abort(source, "input must be a data.frame.")
  }
  if (nrow(raw) == 0L) {
    .render_data_abort(source, "input must contain at least one result row.")
  }
  if (
    is.null(names(raw)) || any(is.na(names(raw))) ||
      any(!nzchar(trimws(names(raw)))) || anyDuplicated(names(raw))
  ) {
    .render_data_abort(source, "column names must be nonempty and distinct.")
  }
  missing <- setdiff(REGRESSION_RESULT_CORE_COLUMNS, names(raw))
  if (length(missing) > 0L) {
    .render_data_abort(
      source, "missing required result column(s): %s", paste(missing, collapse = ", ")
    )
  }
  character_fields <- setdiff(
    REGRESSION_RESULT_CORE_COLUMNS,
    c(
      "estimate", "std_error", "statistic", "p_value", "confidence_level",
      "conf_low", "conf_high", "preparation_top_share",
      "preparation_probability_threshold", "n_input", "n_complete", "n_used",
      "n_missing_dropped", "n_estimator_dropped", "n_dropped"
    )
  )
  for (field in character_fields) {
    raw[[field]] <- .render_result_column(raw[[field]], field, source)
    if (any(is.na(raw[[field]]))) {
      .render_data_abort(source, "column '%s' must not contain missing values.", field)
    }
  }
  nonempty <- c(
    "dataset_id", "audit_id", "model_id", "estimator", "estimator_version",
    "inference_contract_id", "outcome_variable", "term", "vcov_type"
  )
  for (field in nonempty) {
    if (any(is.na(raw[[field]]) | !nzchar(trimws(raw[[field]])))) {
      .render_data_abort(source, "column '%s' must not contain empty values.", field)
    }
  }
  name_fields <- c(
    "explanatory_variables", "control_variables", "fixed_effects",
    "cluster_variables", "estimation_group_variables",
    "preparation_ranking_group_variables", "preparation_scenario_covariates",
    "preparation_candidate_covariates"
  )
  for (field in name_fields) {
    for (value in unique(raw[[field]])) {
      .render_metadata_names(
        value, field, source,
        allow_empty = !(field %in% c(
          "explanatory_variables", "preparation_ranking_group_variables"
        ))
      )
    }
  }
  group_lists <- lapply(
    unique(raw$estimation_group_variables),
    .render_metadata_names,
    field = "estimation_group_variables", source = source
  )
  groups <- unique(unlist(group_lists, use.names = FALSE))
  if (length(intersect(groups, REGRESSION_RESULT_CORE_COLUMNS)) > 0L) {
    .render_data_abort(source, "estimation-group names collide with core result fields.")
  }
  missing_groups <- setdiff(groups, names(raw))
  if (length(missing_groups) > 0L) {
    .render_data_abort(
      source, "missing declared estimation-group column(s): %s",
      paste(missing_groups, collapse = ", ")
    )
  }
  extras <- setdiff(names(raw), c(REGRESSION_RESULT_CORE_COLUMNS, groups))
  if (length(extras) > 0L) {
    .render_data_abort(
      source, "undocumented result column(s): %s", paste(extras, collapse = ", ")
    )
  }
  for (field in groups) {
    raw[[field]] <- .render_result_column(raw[[field]], field, source)
  }
  for (value in unique(raw$estimation_group_variables)) {
    fields <- .render_metadata_names(value, "estimation_group_variables", source)
    rows <- raw$estimation_group_variables == value
    for (field in fields) {
      if (any(is.na(raw[[field]][rows]) | !nzchar(trimws(raw[[field]][rows])))) {
        .render_data_abort(source, "estimation-group column '%s' has empty values.", field)
      }
    }
  }

  fields <- c(REGRESSION_RESULT_CORE_COLUMNS, groups)
  columns <- lapply(fields, function(field) raw[[field]])
  names(columns) <- fields
  # Normalize away source-specific S3 classes and attributes. In particular,
  # a regression_results object and its exported CSV must produce the same
  # validated table without mutating the richer caller-owned object.
  data <- as.data.frame(
    columns,
    optional = TRUE,
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
  numeric_fields <- c(
    "estimate", "std_error", "statistic", "p_value", "confidence_level",
    "conf_low", "conf_high", "preparation_top_share",
    "preparation_probability_threshold"
  )
  count_fields <- c(
    "n_input", "n_complete", "n_used", "n_missing_dropped",
    "n_estimator_dropped", "n_dropped"
  )
  for (field in c(numeric_fields, count_fields)) {
    data[[field]] <- .render_numeric(raw[[field]], field, source)
  }
  for (field in count_fields) {
    value <- data[[field]]
    if (any(value < 0 | value != trunc(value) | value > .Machine$integer.max)) {
      .render_data_abort(source, "column '%s' must contain nonnegative integers.", field)
    }
    data[[field]] <- as.integer(value)
  }
  if (
    any(data$n_used <= 0L | data$n_used > data$n_complete) ||
      any(data$n_complete > data$n_input) ||
      any(data$n_missing_dropped != data$n_input - data$n_complete) ||
      any(data$n_estimator_dropped != data$n_complete - data$n_used) ||
      any(data$n_dropped != data$n_input - data$n_used)
  ) {
    .render_data_abort(source, "observation counts or removal identities are inconsistent.")
  }
  if (any(data$std_error < 0) || any(data$p_value < 0 | data$p_value > 1)) {
    .render_data_abort(source, "standard errors must be nonnegative and p-values in [0, 1].")
  }
  if (any(!(data$confidence_level %in% RENDER_CONFIDENCE_LEVELS))) {
    .render_data_abort(source, "unsupported confidence_level; expected 0.90, 0.95, or 0.99.")
  }
  if (any(data$conf_low > data$estimate | data$conf_high < data$estimate)) {
    .render_data_abort(source, "confidence bounds must contain the saved estimate in order.")
  }
  if (
    any(data$preparation_top_share <= 0 | data$preparation_top_share > 1) ||
      any(data$preparation_probability_threshold <= 0 |
        data$preparation_probability_threshold > 1)
  ) {
    .render_data_abort(source, "preparation shares and thresholds must be in (0, 1].")
  }
  .render_validate_cluster_counts(data, source)
  data
}

.render_combine_result_tables <- function(tables, sources) {
  validated <- Map(
    function(data, source) .render_validate_result_file(data, source),
    tables,
    sources
  )
  columns <- unique(unlist(lapply(validated, names), use.names = FALSE))
  validated <- lapply(validated, function(data) {
    for (field in setdiff(columns, names(data))) {
      data[[field]] <- NA_character_
    }
    data[columns]
  })
  data <- do.call(rbind, validated)
  row.names(data) <- NULL
  .render_validate_interval_rows(data)
  data
}

.render_result_object_tables <- function(results) {
  if (is.data.frame(results)) {
    return(list(tables = list(results), sources = "in-memory results"))
  }
  if (!is.list(results) || inherits(results, "regression_plot_config")) {
    stop(
      paste0(
        "'results' must be one tidy regression-results data.frame or a ",
        "nonempty list of them."
      ),
      call. = FALSE
    )
  }
  if (length(results) == 0L) {
    stop("'results' must not be an empty list.", call. = FALSE)
  }
  valid <- vapply(results, is.data.frame, logical(1))
  if (!all(valid)) {
    stop(
      sprintf(
        "'results' element %d must be a tidy regression-results data.frame.",
        which(!valid)[[1L]]
      ),
      call. = FALSE
    )
  }
  labels <- names(results)
  if (is.null(labels)) {
    labels <- rep("", length(results))
  }
  missing_labels <- is.na(labels) | !nzchar(trimws(labels))
  labels[missing_labels] <- sprintf("element %d", which(missing_labels))
  list(
    tables = unname(results),
    sources = sprintf("in-memory results %s", labels)
  )
}

validate_regression_results <- function(results) {
  collection <- .render_result_object_tables(results)
  .render_combine_result_tables(collection$tables, collection$sources)
}

read_regression_results <- function(results_paths) {
  if (
    !is.character(results_paths) || length(results_paths) == 0L ||
      anyNA(results_paths) || any(!nzchar(trimws(results_paths)))
  ) {
    stop("'results_paths' must be a nonempty character vector of CSV paths.",
      call. = FALSE)
  }
  if (any(!grepl("\\.csv$", basename(results_paths), ignore.case = TRUE))) {
    stop("Every regression-results path must end in '.csv'.", call. = FALSE)
  }
  missing <- !file.exists(results_paths)
  if (any(missing)) {
    stop(
      sprintf(
        "Regression-results CSV does not exist: %s",
        results_paths[which(missing)[[1L]]]
      ),
      call. = FALSE
    )
  }
  directories <- file.info(results_paths)$isdir %in% TRUE
  if (any(directories)) {
    stop(
      sprintf(
        "Regression-results path is a directory: %s",
        results_paths[which(directories)[[1L]]]
      ),
      call. = FALSE
    )
  }
  unreadable <- file.access(results_paths, 4L) != 0L
  if (any(unreadable)) {
    stop(
      sprintf(
        "Regression-results CSV is not readable: %s",
        results_paths[which(unreadable)[[1L]]]
      ),
      call. = FALSE
    )
  }
  resolved <- normalizePath(results_paths, winslash = "/", mustWork = TRUE)
  if (anyDuplicated(resolved)) {
    stop("'results_paths' must refer to distinct CSV files.", call. = FALSE)
  }
  files <- Map(
    function(path, label) .render_read_csv(path, label),
    resolved,
    results_paths
  )
  .render_combine_result_tables(files, results_paths)
}

load_regression_results <- function(config) {
  config <- .render_as_config(config)
  read_regression_results(config$resolved_results_paths)
}

.render_validate_interval_rows <- function(data) {
  # Files can carry different grouping schemas. Undeclared columns must not
  # split a coefficient's intervals and bypass their consistency checks.
  for (specification in unique(data$estimation_group_variables)) {
    group_fields <- .render_metadata_names(
      specification, "estimation_group_variables", "combined data"
    )
    .render_validate_interval_group(
      data[data$estimation_group_variables == specification, , drop = FALSE],
      group_fields
    )
  }
  invisible(data)
}

.render_validate_interval_group <- function(data, group_fields) {
  keys <- c(
    "dataset_id", "audit_id", "model_id", "outcome_variable", "term",
    "estimation_group_variables", group_fields
  )
  ordered <- do.call(
    order, c(unname(data[keys]), list(na.last = TRUE, method = "radix"))
  )
  boundaries <- rep(FALSE, max(nrow(data) - 1L, 0L))
  for (field in keys) {
    values <- data[[field]][ordered]
    left <- head(values, -1L)
    right <- tail(values, -1L)
    different <- is.na(left) != is.na(right) |
      (!is.na(left) & !is.na(right) & left != right)
    boundaries <- boundaries | different
  }
  group_ids <- cumsum(c(TRUE, boundaries))
  constant_fields <- setdiff(
    REGRESSION_RESULT_CORE_COLUMNS,
    c("confidence_level", "conf_low", "conf_high")
  )
  for (indices in split(ordered, group_ids)) {
    rows <- data[indices, , drop = FALSE]
    if (anyDuplicated(rows$confidence_level)) {
      .render_data_abort("combined data", "duplicate saved coefficient/interval keys.")
    }
    if (nrow(unique(rows[constant_fields])) != 1L) {
      .render_data_abort(
        "combined data", "coefficient statistics or metadata disagree across saved intervals."
      )
    }
    rows <- rows[order(rows$confidence_level), , drop = FALSE]
    tolerance <- 64 * .Machine$double.eps *
      max(1, abs(rows$conf_low), abs(rows$conf_high))
    if (any(diff(rows$conf_low) > tolerance) ||
        any(diff(rows$conf_high) < -tolerance)) {
      .render_data_abort("combined data", "saved confidence bounds are not nested by level.")
    }
  }
  invisible(data)
}

.render_selected_tokens <- function(data, field) {
  if (!(field %in% names(data))) {
    .render_data_abort("selected data", "missing configured column '%s'.", field)
  }
  values <- as.character(data[[field]])
  if (any(is.na(values) | !nzchar(trimws(values)))) {
    .render_data_abort("selected data", "plot dimension '%s' has empty values.", field)
  }
  values
}

.render_source_identities <- function(data) {
  unique(data.frame(
    audit_id = as.character(data$audit_id),
    dataset_id = as.character(data$dataset_id),
    stringsAsFactors = FALSE
  ))
}

.render_require_source_coverage <- function(data, expected, selection) {
  observed <- .render_source_identities(data)
  retained <- vapply(seq_len(nrow(expected)), function(index) {
    any(
      observed$audit_id == expected$audit_id[[index]] &
        observed$dataset_id == expected$dataset_id[[index]]
    )
  }, logical(1))
  if (any(!retained)) {
    missing <- expected[!retained, , drop = FALSE]
    labels <- sprintf(
      "audit_id='%s', dataset_id='%s'",
      missing$audit_id,
      missing$dataset_id
    )
    .render_data_abort(
      "selected data",
      "%s removed all rows for source(s): %s. Supply a compatible selection or an explicitly inspected result subset.",
      selection,
      paste(labels, collapse = "; ")
    )
  }
  invisible(data)
}

.render_order_values <- function(values, configured, field) {
  observed <- unique(values)
  if (length(configured) > 0L) {
    missing <- setdiff(observed, configured)
    extra <- setdiff(configured, observed)
    if (length(missing) > 0L || length(extra) > 0L || anyDuplicated(configured)) {
      .render_data_abort(
        "selected data", "%s must be a complete permutation (omitted: %s; unknown: %s).",
        field,
        if (length(missing)) paste(missing, collapse = ", ") else "none",
        if (length(extra)) paste(extra, collapse = ", ") else "none"
      )
    }
    return(configured)
  }
  numeric <- suppressWarnings(as.numeric(observed))
  if (all(is.finite(numeric))) {
    observed[order(numeric, observed, method = "radix")]
  } else {
    sort(observed, method = "radix")
  }
}

.render_period_positions <- function(period_order) {
  values <- suppressWarnings(as.numeric(period_order))
  gaps <- diff(values)
  if (
    all(is.finite(values)) && !anyDuplicated(values) &&
      all(is.finite(gaps) & gaps > 0) &&
      is.finite(max(values) - min(values))
  ) {
    # Reserve enough finite space for series dodging and interval caps.
    padding <- if (length(gaps)) .15 * min(gaps) + .4 else 1.9
    limits <- c(min(values) - padding, max(values) + padding)
    span <- diff(limits)
    expanded <- limits + c(-.05, .05) * span
    if (
      all(is.finite(limits)) && is.finite(span) && span > 0 &&
        all(is.finite(expanded)) && is.finite(diff(expanded))
    ) {
      return(values)
    }
  }
  10 * seq_along(period_order)
}

prepare_regression_plot_data <- function(results = NULL, config = NULL) {
  # Preserve the original one-argument file workflow while making the data
  # source explicit for interactive use.
  if (
    is.null(config) &&
      (
        inherits(results, "regression_plot_config") ||
          (is.character(results) && length(results) == 1L && !is.na(results))
      )
  ) {
    config <- results
    results <- NULL
  }
  if (is.null(config)) {
    stop(
      "'config' must be supplied when plotting in-memory regression results.",
      call. = FALSE
    )
  }
  config <- .regression_plot_as_config(config)
  if (is.null(results)) {
    if (!inherits(config, "render_config")) {
      stop(
        paste0(
          "'results' must be supplied with an in-memory regression_plot_config; ",
          "only a render_config can load result CSVs."
        ),
        call. = FALSE
      )
    }
    data <- load_regression_results(config)
  } else if (is.character(results)) {
    data <- read_regression_results(results)
  } else {
    data <- validate_regression_results(results)
  }
  expected_sources <- .render_source_identities(data)
  selected <- data$term == config$term &
    data$confidence_level == config$confidence_level
  data <- data[selected, , drop = FALSE]
  .render_require_source_coverage(
    data,
    expected_sources,
    "the term and confidence-level selection"
  )
  if (nrow(data) == 0L) {
    .render_data_abort(
      "selected data", "no rows match term '%s' and confidence level %.2f.",
      config$term, config$confidence_level
    )
  }
  mapping <- config$outcome_by_panel
  if (!is.null(config$outcome_variable)) {
    data <- data[data$outcome_variable == config$outcome_variable, , drop = FALSE]
    .render_require_source_coverage(
      data,
      expected_sources,
      "the outcome selection"
    )
    if (nrow(data) == 0L) {
      .render_data_abort(
        "selected data",
        "no rows match outcome_variable '%s', term '%s', and confidence level %.2f.",
        config$outcome_variable, config$term, config$confidence_level
      )
    }
  } else {
    if (is.null(config$panel_variable)) {
      .render_data_abort(
        "selected data", "outcome_by_panel requires a configured panel_variable."
      )
    }
    panel <- .render_selected_tokens(data, config$panel_variable)
    observed_panels <- unique(panel)
    if (!setequal(names(mapping), observed_panels)) {
      .render_data_abort(
        "selected data", "outcome_by_panel must cover every observed panel exactly."
      )
    }
    keep <- data$outcome_variable == unname(mapping[panel])
    filtered <- data[keep, , drop = FALSE]
    .render_require_source_coverage(
      filtered,
      expected_sources,
      "the outcome selection"
    )
    missing_panels <- setdiff(observed_panels, unique(panel[keep]))
    if (length(missing_panels) > 0L) {
      .render_data_abort(
        "selected data",
        "the outcome_by_panel selection has no saved result rows for panel value(s): %s.",
        paste(missing_panels, collapse = ", ")
      )
    }
    data <- filtered
  }
  .render_require_source_coverage(
    data,
    expected_sources,
    "the outcome selection"
  )
  panel <- if (is.null(config$panel_variable)) {
    rep(".single_panel", nrow(data))
  } else {
    .render_selected_tokens(data, config$panel_variable)
  }
  period <- .render_selected_tokens(data, config$period_variable)
  series <- if (is.null(config$series_variable)) {
    rep("", nrow(data))
  } else {
    .render_selected_tokens(data, config$series_variable)
  }
  dimensions <- c(
    config$period_variable, config$panel_variable, config$series_variable
  )
  for (field in RENDER_GLOBAL_COMPATIBILITY_COLUMNS) {
    if (length(unique(data[[field]])) != 1L) {
      .render_data_abort(
        "selected data", "incompatible '%s' across selected results.", field
      )
    }
  }
  panel_rows <- unname(split(seq_len(nrow(data)), panel, drop = TRUE))
  for (rows in panel_rows) {
    panel_label <- panel[[rows[[1L]]]]
    for (field in RENDER_PANEL_COMPATIBILITY_COLUMNS) {
      if (length(unique(data[[field]][rows])) != 1L) {
        .render_data_abort(
          "selected data",
          "incompatible '%s' within panel '%s'.",
          field,
          panel_label
        )
      }
    }
    group_fields <- .render_metadata_names(
      data$estimation_group_variables[[rows[[1L]]]],
      "estimation_group_variables",
      "selected data"
    )
    for (field in setdiff(group_fields, dimensions)) {
      if (length(unique(data[[field]][rows])) != 1L) {
        .render_data_abort(
          "selected data",
          paste0(
            "unplotted estimation-group column '%s' varies within panel ",
            "'%s'; map it or supply a slice."
          ),
          field,
          panel_label
        )
      }
    }
  }
  keys <- data.frame(panel = panel, period = period, series = series)
  if (anyDuplicated(keys)) {
    .render_data_abort(
      "selected data", "duplicate plotting keys for the configured panel, period, and series."
    )
  }
  panel_order <- if (is.null(config$panel_variable)) {
    ".single_panel"
  } else {
    .render_order_values(panel, config$panel_order, "panel_order")
  }
  period_order <- .render_order_values(period, config$period_order, "period_order")
  series_order <- if (is.null(config$series_variable)) {
    character()
  } else {
    .render_order_values(series, config$series_order, "series_order")
  }
  if (is.null(config$panel_variable)) {
    panel_labels <- stats::setNames(config$outcome_variable, panel_order)
  } else {
    if (length(setdiff(names(config$panel_labels), panel_order)) > 0L) {
      .render_data_abort("selected data", "panel_labels contains unknown panel keys.")
    }
    panel_labels <- stats::setNames(panel_order, panel_order)
    panel_labels[names(config$panel_labels)] <- config$panel_labels
  }
  period_positions <- .render_period_positions(period_order)
  minimum_gap <- if (length(period_positions) > 1L) {
    min(diff(period_positions))
  } else {
    10
  }
  offsets <- if (length(series_order) > 1L) {
    seq(-0.15, 0.15, length.out = length(series_order)) * minimum_gap
  } else {
    0
  }
  data$.plot_panel <- panel
  data$.plot_period <- period
  data$.plot_series <- series
  data$.plot_x <- period_positions[match(period, period_order)]
  if (length(series_order) > 0L) {
    data$.plot_x <- data$.plot_x + offsets[match(series, series_order)]
  }
  data$.plot_alpha <- ifelse(data$p_value < config$significance_level, 1, 0.3)
  ordered <- order(
    match(panel, panel_order), match(period, period_order),
    match(series, series_order), na.last = TRUE, method = "radix"
  )
  data <- data[ordered, , drop = FALSE]
  row.names(data) <- NULL
  cap_width <- if (length(offsets) > 1L) {
    min(0.8, min(diff(offsets)) * 0.6)
  } else {
    0.8
  }
  structure(
    list(
      data = data, config = config, period_order = period_order,
      panel_order = panel_order, series_order = series_order,
      period_positions = period_positions, panel_labels = panel_labels,
      cap_width = cap_width
    ),
    class = c("regression_plot_data", "list")
  )
}
