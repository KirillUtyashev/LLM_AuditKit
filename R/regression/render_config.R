REGRESSION_PLOT_CONFIG_KEYS <- c(
  "term", "outcome_variable", "confidence_level", "period_variable",
  "series_variable", "panel_variable", "outcome_by_panel",
  "period_order", "series_order", "panel_order", "panel_labels", "x_label",
  "y_label", "y_limits", "y_break_interval", "significance_level",
  "panel_columns"
)

RENDER_CONFIG_KEYS <- c(
  "results_paths", "output_path", REGRESSION_PLOT_CONFIG_KEYS,
  "width", "height", "dpi"
)

.render_config_abort <- function(config_path, format, ...) {
  detail <- sprintf(format, ...)
  if (is.null(config_path)) {
    stop(sprintf("Invalid regression plot config: %s", detail), call. = FALSE)
  }
  stop(
    sprintf(
      "Invalid render config '%s': %s",
      config_path,
      detail
    ),
    call. = FALSE
  )
}

.render_config_yaml_sequence <- function(value) {
  structure(value, class = c("render_yaml_sequence", "list"))
}

.render_config_yaml_mapping <- function(value) {
  structure(value, class = c("render_yaml_mapping", "list"))
}

.render_config_string <- function(value, field, config_path) {
  if (
    !is.character(value) || length(value) != 1L ||
      is.na(value) || !nzchar(trimws(value))
  ) {
    .render_config_abort(
      config_path, "'%s' must be one nonempty string.", field
    )
  }
  value
}

.render_config_number <- function(value, field, config_path) {
  if (
    !is.numeric(value) || length(value) != 1L ||
      is.na(value) || !is.finite(value)
  ) {
    .render_config_abort(
      config_path, "'%s' must be one finite number.", field
    )
  }
  as.numeric(value)
}

.render_config_positive_number <- function(value, field, config_path) {
  value <- .render_config_number(value, field, config_path)
  if (value <= 0) {
    .render_config_abort(config_path, "'%s' must be positive.", field)
  }
  value
}

.render_config_positive_integer <- function(value, field, config_path) {
  value <- .render_config_positive_number(value, field, config_path)
  if (value != floor(value) || value > .Machine$integer.max) {
    .render_config_abort(
      config_path,
      "'%s' must be a positive integer no larger than %s.",
      field,
      .Machine$integer.max
    )
  }
  as.integer(value)
}

.render_config_sequence <- function(
  value, field, config_path, strings_only = FALSE, allow_empty = TRUE
) {
  if (!inherits(value, "render_yaml_sequence")) {
    .render_config_abort(config_path, "'%s' must be a YAML list.", field)
  }
  if (!allow_empty && length(value) == 0L) {
    .render_config_abort(config_path, "'%s' must not be empty.", field)
  }

  values <- vapply(value, function(element) {
    if (strings_only) {
      return(.render_config_string(element, field, config_path))
    }
    valid <- length(element) == 1L &&
      (is.character(element) || is.numeric(element) || is.logical(element)) &&
      !is.na(element)
    if (valid && is.character(element)) {
      valid <- nzchar(trimws(element))
    }
    if (valid && is.numeric(element)) {
      valid <- is.finite(element)
    }
    if (!valid) {
      .render_config_abort(
        config_path,
        "'%s' must contain only nonempty strings, finite numbers, or logical values.",
        field
      )
    }
    as.character(element)
  }, character(1), USE.NAMES = FALSE)

  duplicate <- duplicated(values)
  if (any(duplicate)) {
    .render_config_abort(
      config_path,
      "'%s' contains duplicate value '%s'.",
      field,
      values[which(duplicate)[1L]]
    )
  }
  values
}

.render_config_map <- function(value, field, config_path) {
  if (!inherits(value, "render_yaml_mapping")) {
    .render_config_abort(config_path, "'%s' must be a YAML mapping.", field)
  }
  if (length(value) == 0L) {
    return(character())
  }
  keys <- names(value)
  if (is.null(keys) || anyNA(keys) || any(!nzchar(trimws(keys)))) {
    .render_config_abort(config_path, "'%s' has an empty mapping key.", field)
  }
  if (anyDuplicated(keys)) {
    .render_config_abort(config_path, "'%s' has duplicate mapping keys.", field)
  }
  values <- vapply(value, function(element) {
    .render_config_string(element, field, config_path)
  }, character(1), USE.NAMES = FALSE)
  stats::setNames(values, keys)
}

.render_config_column <- function(value, field, config_path) {
  value <- .render_config_string(value, field, config_path)
  if (
    !grepl("^[A-Za-z][A-Za-z0-9_]*$", value) ||
      make.names(value) != value
  ) {
    .render_config_abort(
      config_path, "'%s' contains invalid column name '%s'.", field, value
    )
  }
  value
}

.render_config_direct_sequence <- function(value, field, config_path) {
  if (
    !(is.character(value) || is.numeric(value) || is.logical(value)) ||
      is.object(value)
  ) {
    .render_config_abort(
      config_path,
      "'%s' must be an atomic character, numeric, or logical vector.",
      field
    )
  }
  values <- vapply(as.list(value), function(element) {
    valid <- length(element) == 1L && !is.na(element)
    if (valid && is.character(element)) {
      valid <- nzchar(trimws(element))
    }
    if (valid && is.numeric(element)) {
      valid <- is.finite(element)
    }
    if (!valid) {
      .render_config_abort(
        config_path,
        "'%s' must contain only nonempty strings, finite numbers, or logical values.",
        field
      )
    }
    as.character(element)
  }, character(1), USE.NAMES = FALSE)
  duplicate <- duplicated(values)
  if (any(duplicate)) {
    .render_config_abort(
      config_path,
      "'%s' contains duplicate value '%s'.",
      field,
      values[which(duplicate)[1L]]
    )
  }
  values
}

.render_config_direct_map <- function(value, field, config_path) {
  if (!is.character(value) || is.object(value)) {
    .render_config_abort(
      config_path, "'%s' must be a named character vector.", field
    )
  }
  if (length(value) == 0L) {
    return(character())
  }
  keys <- names(value)
  if (
    is.null(keys) || anyNA(keys) || any(!nzchar(trimws(keys))) ||
      anyNA(value) || any(!nzchar(trimws(value)))
  ) {
    .render_config_abort(
      config_path,
      "'%s' must be a named character vector with nonempty names and values.",
      field
    )
  }
  if (anyDuplicated(keys)) {
    .render_config_abort(config_path, "'%s' has duplicate mapping keys.", field)
  }
  value
}

.validate_regression_plot_config <- function(raw, config_path = NULL, yaml = FALSE) {
  sequence_value <- function(field) {
    if (yaml) {
      .render_config_sequence(raw[[field]], field, config_path)
    } else {
      .render_config_direct_sequence(raw[[field]], field, config_path)
    }
  }
  map_value <- function(field) {
    if (yaml) {
      .render_config_map(raw[[field]], field, config_path)
    } else {
      .render_config_direct_map(raw[[field]], field, config_path)
    }
  }

  config <- list()
  config$term <- .render_config_string(raw$term, "term", config_path)
  config["outcome_variable"] <- list(if (is.null(raw$outcome_variable)) {
    NULL
  } else {
    .render_config_column(raw$outcome_variable, "outcome_variable", config_path)
  })
  config$confidence_level <- .render_config_number(
    raw$confidence_level, "confidence_level", config_path
  )
  if (!config$confidence_level %in% c(0.90, 0.95, 0.99)) {
    .render_config_abort(
      config_path, "'confidence_level' must be one of 0.90, 0.95, or 0.99."
    )
  }
  config$period_variable <- .render_config_column(
    raw$period_variable, "period_variable", config_path
  )
  for (field in c("series_variable", "panel_variable")) {
    config[field] <- list(if (is.null(raw[[field]])) {
      NULL
    } else {
      .render_config_column(raw[[field]], field, config_path)
    })
  }
  dimensions <- unlist(
    config[c("period_variable", "series_variable", "panel_variable")],
    use.names = FALSE
  )
  if (anyDuplicated(dimensions)) {
    .render_config_abort(
      config_path,
      "'period_variable' and non-null 'series_variable' and 'panel_variable' must be distinct."
    )
  }

  config$outcome_by_panel <- map_value("outcome_by_panel")
  if (length(config$outcome_by_panel) > 0L) {
    config$outcome_by_panel[] <- vapply(
      config$outcome_by_panel,
      .render_config_column,
      character(1),
      field = "outcome_by_panel",
      config_path = config_path,
      USE.NAMES = FALSE
    )
  }
  has_outcome <- !is.null(config$outcome_variable)
  has_outcome_map <- length(config$outcome_by_panel) > 0L
  if (identical(has_outcome, has_outcome_map)) {
    .render_config_abort(
      config_path,
      "exactly one of non-null 'outcome_variable' or nonempty 'outcome_by_panel' must be supplied."
    )
  }
  if (has_outcome_map && is.null(config$panel_variable)) {
    .render_config_abort(
      config_path,
      "'outcome_by_panel' requires a non-null 'panel_variable'."
    )
  }

  for (field in c("period_order", "series_order", "panel_order")) {
    config[[field]] <- sequence_value(field)
  }
  config$panel_labels <- map_value("panel_labels")
  if (is.null(config$series_variable) && length(config$series_order) > 0L) {
    .render_config_abort(
      config_path, "'series_order' must be empty when 'series_variable' is null."
    )
  }
  if (
    is.null(config$panel_variable) &&
      (length(config$panel_order) > 0L || length(config$panel_labels) > 0L)
  ) {
    .render_config_abort(
      config_path,
      "'panel_order' and 'panel_labels' must be empty when 'panel_variable' is null."
    )
  }

  for (field in c("x_label", "y_label")) {
    config[[field]] <- .render_config_string(raw[[field]], field, config_path)
  }
  valid_limits <- if (yaml) {
    inherits(raw$y_limits, "render_yaml_sequence")
  } else {
    is.numeric(raw$y_limits) && !is.object(raw$y_limits)
  }
  if (!valid_limits || length(raw$y_limits) != 2L) {
    qualifier <- if (yaml) "a YAML list" else "a numeric vector"
    .render_config_abort(
      config_path,
      "'y_limits' must be %s of two finite increasing bounds.",
      qualifier
    )
  }
  config$y_limits <- vapply(raw$y_limits, function(value) {
    .render_config_number(value, "y_limits", config_path)
  }, numeric(1), USE.NAMES = FALSE)
  if (config$y_limits[1L] >= config$y_limits[2L]) {
    .render_config_abort(config_path, "'y_limits' must have increasing bounds.")
  }
  config$y_break_interval <- .render_config_positive_number(
    raw$y_break_interval, "y_break_interval", config_path
  )
  config$significance_level <- .render_config_number(
    raw$significance_level, "significance_level", config_path
  )
  if (config$significance_level < 0 || config$significance_level > 1) {
    .render_config_abort(config_path, "'significance_level' must be in [0, 1].")
  }
  config$panel_columns <- .render_config_positive_integer(
    raw$panel_columns, "panel_columns", config_path
  )
  break_ratio <- (config$y_limits[2L] - config$y_limits[1L]) /
    config$y_break_interval
  if (!is.finite(break_ratio) || floor(break_ratio) + 1 > 10000) {
    .render_config_abort(
      config_path,
      "'y_limits' and 'y_break_interval' must imply at most 10,000 y-axis breaks; increase the spacing or narrow the limits."
    )
  }

  structure(
    config[REGRESSION_PLOT_CONFIG_KEYS],
    class = c("regression_plot_config", "list")
  )
}

regression_plot_config <- function(
  term,
  period_variable,
  outcome_variable = NULL,
  confidence_level = 0.95,
  series_variable = NULL,
  panel_variable = NULL,
  outcome_by_panel = character(),
  period_order = character(),
  series_order = character(),
  panel_order = character(),
  panel_labels = character(),
  x_label = "Period",
  y_label = "Coefficient estimate",
  y_limits = c(-0.3, 0.3),
  y_break_interval = 0.1,
  significance_level = 0.05,
  panel_columns = 2L
) {
  .validate_regression_plot_config(
    mget(REGRESSION_PLOT_CONFIG_KEYS, envir = environment(), inherits = FALSE),
    yaml = FALSE
  )
}

load_render_config <- function(config_path) {
  if (
    !is.character(config_path) || length(config_path) != 1L ||
      is.na(config_path) || !nzchar(trimws(config_path))
  ) {
    stop("Render config path must be one nonempty string.", call. = FALSE)
  }
  if (!file.exists(config_path) || isTRUE(file.info(config_path)$isdir)) {
    stop(
      sprintf("Render config file does not exist: %s", config_path),
      call. = FALSE
    )
  }
  if (file.access(config_path, mode = 4L) != 0L) {
    stop(
      sprintf("Render config file is not readable: %s", config_path),
      call. = FALSE
    )
  }
  if (!requireNamespace("yaml", quietly = TRUE)) {
    stop("Package 'yaml' is required to load render config.", call. = FALSE)
  }

  config_path <- normalizePath(config_path, winslash = "/", mustWork = TRUE)
  config_directory <- dirname(config_path)
  raw <- tryCatch(
    withCallingHandlers(
      yaml::read_yaml(
        config_path,
        eval.expr = FALSE,
        handlers = list(
          seq = .render_config_yaml_sequence,
          map = .render_config_yaml_mapping
        )
      ),
      warning = function(warning) stop(conditionMessage(warning), call. = FALSE)
    ),
    error = function(error) {
      .render_config_abort(
        config_path, "YAML could not be parsed: %s", conditionMessage(error)
      )
    }
  )
  if (!inherits(raw, "render_yaml_mapping")) {
    .render_config_abort(config_path, "top level must be a YAML mapping.")
  }
  unknown <- setdiff(names(raw), RENDER_CONFIG_KEYS)
  if (length(unknown) > 0L) {
    .render_config_abort(
      config_path, "unknown field(s): %s", paste(unknown, collapse = ", ")
    )
  }
  required <- c("results_paths", "output_path", "term", "period_variable")
  missing <- setdiff(required, names(raw))
  if (length(missing) > 0L) {
    .render_config_abort(
      config_path, "missing required field(s): %s", paste(missing, collapse = ", ")
    )
  }
  defaults <- list(
    outcome_variable = NULL,
    confidence_level = 0.95,
    series_variable = NULL,
    panel_variable = NULL,
    outcome_by_panel = .render_config_yaml_mapping(list()),
    period_order = .render_config_yaml_sequence(list()),
    series_order = .render_config_yaml_sequence(list()),
    panel_order = .render_config_yaml_sequence(list()),
    panel_labels = .render_config_yaml_mapping(list()),
    x_label = "Period",
    y_label = "Coefficient estimate",
    y_limits = .render_config_yaml_sequence(list(-0.3, 0.3)),
    y_break_interval = 0.1,
    significance_level = 0.05,
    panel_columns = 2L,
    width = 12,
    height = 8,
    dpi = 300L
  )
  for (field in setdiff(names(defaults), names(raw))) {
    raw[field] <- defaults[field]
  }

  results_paths <- .render_config_sequence(
    raw$results_paths, "results_paths", config_path,
    strings_only = TRUE, allow_empty = FALSE
  )
  output_path <- .render_config_string(raw$output_path, "output_path", config_path)
  plot_config <- .validate_regression_plot_config(
    raw[REGRESSION_PLOT_CONFIG_KEYS], config_path = config_path, yaml = TRUE
  )
  width <- .render_config_positive_number(raw$width, "width", config_path)
  height <- .render_config_positive_number(raw$height, "height", config_path)
  dpi <- .render_config_positive_integer(raw$dpi, "dpi", config_path)
  config <- c(
    list(results_paths = results_paths, output_path = output_path),
    unclass(plot_config),
    list(width = width, height = height, dpi = dpi)
  )
  for (field in c("width", "height")) {
    pixels <- config[[field]] * config$dpi
    if (!is.finite(pixels) || pixels < 1 || pixels > .Machine$integer.max) {
      .render_config_abort(
        config_path,
        "'%s' times 'dpi' must be finite and between 1 and %s pixels.",
        field,
        .Machine$integer.max
      )
    }
  }

  configured_paths <- c(config$results_paths, config$output_path)
  unresolved_home <- startsWith(configured_paths, "~") &
    startsWith(path.expand(configured_paths), "~")
  if (any(unresolved_home)) {
    .render_config_abort(
      config_path,
      "home-directory shorthand cannot be expanded in path '%s'.",
      configured_paths[which(unresolved_home)[1L]]
    )
  }
  if (any(tolower(tools::file_ext(config$results_paths)) != "csv")) {
    .render_config_abort(config_path, "every 'results_paths' entry must end in '.csv'.")
  }
  if (tolower(tools::file_ext(config$output_path)) != "png") {
    .render_config_abort(config_path, "'output_path' must end in '.png'.")
  }
  resolved_results_paths <- vapply(config$results_paths, function(path) {
    resolved <- .regression_config_resolve_path(path, config_directory)
    if (!file.exists(resolved)) {
      .render_config_abort(config_path, "input result CSV does not exist: %s", resolved)
    }
    if (isTRUE(file.info(resolved)$isdir)) {
      .render_config_abort(config_path, "input result path is a directory: %s", resolved)
    }
    if (file.access(resolved, mode = 4L) != 0L) {
      .render_config_abort(config_path, "input result CSV is not readable: %s", resolved)
    }
    resolved
  }, character(1), USE.NAMES = FALSE)
  if (anyDuplicated(resolved_results_paths)) {
    .render_config_abort(config_path, "'results_paths' must resolve to distinct input CSVs.")
  }
  resolved_output_path <- .regression_config_resolve_path(
    config$output_path, config_directory
  )
  if (resolved_output_path %in% resolved_results_paths) {
    .render_config_abort(config_path, "'output_path' must be distinct from every input CSV.")
  }
  if (file.exists(resolved_output_path) && isTRUE(file.info(resolved_output_path)$isdir)) {
    .render_config_abort(config_path, "output PNG path is a directory: %s", resolved_output_path)
  }

  config$results_paths <- vapply(
    config$results_paths, .regression_config_path_label,
    character(1), USE.NAMES = FALSE
  )
  config$output_path <- .regression_config_path_label(config$output_path)
  structure(
    c(
      config[RENDER_CONFIG_KEYS],
      list(
        config_path = config_path,
        config_directory = config_directory,
        resolved_results_paths = resolved_results_paths,
        resolved_output_path = resolved_output_path
      )
    ),
    class = c("render_config", "regression_plot_config", "list")
  )
}

.regression_plot_as_config <- function(config) {
  if (is.character(config) && length(config) == 1L && !is.na(config)) {
    config <- load_render_config(config)
  }
  if (!inherits(config, "regression_plot_config")) {
    stop(
      "'config' must be a regression_plot_config, render_config, or one YAML config path.",
      call. = FALSE
    )
  }
  config
}

.render_as_config <- function(config) {
  if (is.character(config) && length(config) == 1L && !is.na(config)) {
    config <- load_render_config(config)
  }
  if (!inherits(config, "render_config")) {
    stop(
      "'config' must be a render_config or one YAML config path.",
      call. = FALSE
    )
  }
  config
}
