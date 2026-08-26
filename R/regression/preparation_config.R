PREPARATION_CONFIG_KEYS <- c(
  "input_paths",
  "output_path",
  "top_share",
  "probability_threshold",
  "ranking_group_variables",
  "scenario_covariates",
  "candidate_covariates"
)

PREPARATION_RESERVED_COLUMNS <- c(
  "source_file",
  "scenario_id",
  "persona_id",
  "model_config_id",
  "result_status",
  "candidate_count",
  "candidate_id",
  "candidate_index",
  "city",
  "year",
  "pick",
  "log_probability",
  "raw_pick",
  "raw_log_probability",
  "pick_top",
  "pick_threshold",
  "preparation_top_share",
  "preparation_probability_threshold",
  "preparation_ranking_group_variables",
  "preparation_scenario_covariates",
  "preparation_candidate_covariates"
)

PREPARATION_PRE_RANKING_COLUMNS <- c(
  "source_file",
  "scenario_id",
  "persona_id",
  "model_config_id",
  "candidate_id",
  "candidate_index",
  "candidate_count",
  "city",
  "year"
)

.preparation_abort <- function(config_path, format, ...) {
  message <- sprintf(format, ...)
  stop(
    sprintf("Invalid preparation config '%s': %s", config_path, message),
    call. = FALSE
  )
}

.preparation_yaml_sequence <- function(value) {
  structure(value, class = c("yaml_sequence", "list"))
}

.preparation_string_sequence <- function(
  value,
  field,
  config_path,
  allow_empty = FALSE
) {
  if (!inherits(value, "yaml_sequence")) {
    .preparation_abort(
      config_path,
      "'%s' must be a YAML list of strings.",
      field
    )
  }

  if (!allow_empty && length(value) == 0L) {
    .preparation_abort(config_path, "'%s' must not be empty.", field)
  }

  values <- vapply(
    value,
    function(element) {
      if (
        !is.character(element) ||
          length(element) != 1L ||
          is.na(element) ||
          !nzchar(trimws(element))
      ) {
        .preparation_abort(
          config_path,
          "'%s' must contain only nonempty strings.",
          field
        )
      }
      element
    },
    character(1)
  )

  duplicate <- duplicated(values)
  if (any(duplicate)) {
    .preparation_abort(
      config_path,
      "'%s' contains duplicate value '%s'.",
      field,
      values[which(duplicate)[1L]]
    )
  }

  values
}

.preparation_scalar_string <- function(value, field, config_path) {
  if (
    inherits(value, "yaml_sequence") ||
      !is.character(value) ||
      length(value) != 1L ||
      is.na(value) ||
      !nzchar(trimws(value))
  ) {
    .preparation_abort(
      config_path,
      "'%s' must be one nonempty string.",
      field
    )
  }
  value
}

.preparation_probability <- function(value, field, config_path) {
  if (
    !is.numeric(value) ||
      is.logical(value) ||
      length(value) != 1L ||
      is.na(value) ||
      !is.finite(value) ||
      value <= 0 ||
      value > 1
  ) {
    .preparation_abort(
      config_path,
      "'%s' must be one finite number in (0, 1].",
      field
    )
  }
  as.numeric(value)
}

.preparation_validate_names <- function(
  values,
  field,
  config_path,
  reject_reserved = FALSE
) {
  invalid <- !grepl("^[A-Za-z][A-Za-z0-9_]*$", values)
  if (any(invalid)) {
    .preparation_abort(
      config_path,
      "'%s' contains invalid column name '%s'.",
      field,
      values[which(invalid)[1L]]
    )
  }

  if (reject_reserved) {
    reserved <- values %in% PREPARATION_RESERVED_COLUMNS
    if (any(reserved)) {
      .preparation_abort(
        config_path,
        "'%s' cannot include reserved column '%s'.",
        field,
        values[which(reserved)[1L]]
      )
    }

    payload <- grepl(
      "prompt|response|comment|job_posting_text|resume_text",
      values,
      ignore.case = TRUE
    )
    if (any(payload)) {
      .preparation_abort(
        config_path,
        "'%s' cannot include payload-text field '%s'.",
        field,
        values[which(payload)[1L]]
      )
    }
  }

  invisible(values)
}

.preparation_is_absolute_path <- function(path) {
  startsWith(path, "~") ||
    grepl("^/", path) ||
    grepl("^[A-Za-z]:[/\\\\]", path) ||
    grepl("^\\\\\\\\", path)
}

.preparation_normalize_lexical_path <- function(path) {
  path <- gsub("\\\\", "/", path)
  prefix <- ""
  remainder <- path
  if (startsWith(path, "//")) {
    prefix <- "//"
    remainder <- substring(path, 3L)
  } else if (startsWith(path, "/")) {
    prefix <- "/"
    remainder <- substring(path, 2L)
  } else if (grepl("^[A-Za-z]:/", path)) {
    prefix <- substring(path, 1L, 3L)
    remainder <- substring(path, 4L)
  }

  parts <- strsplit(remainder, "/", fixed = TRUE)[[1L]]
  normalized <- character()

  for (part in parts) {
    if (!nzchar(part) || identical(part, ".")) {
      next
    }
    if (identical(part, "..")) {
      if (length(normalized) > 0L && tail(normalized, 1L) != "..") {
        normalized <- head(normalized, -1L)
      } else if (!nzchar(prefix)) {
        normalized <- c(normalized, part)
      }
    } else {
      normalized <- c(normalized, part)
    }
  }

  if (length(normalized) == 0L) {
    if (nzchar(prefix)) prefix else "."
  } else {
    paste0(prefix, paste(normalized, collapse = "/"))
  }
}

.preparation_path_label <- function(path) {
  if (startsWith(path, "~")) {
    path <- path.expand(path)
  }
  .preparation_normalize_lexical_path(path)
}

.preparation_resolve_path <- function(path, config_directory, must_work) {
  expanded <- path.expand(path)
  candidate <- if (.preparation_is_absolute_path(path)) {
    expanded
  } else {
    file.path(config_directory, expanded)
  }
  normalizePath(candidate, winslash = "/", mustWork = must_work)
}

.preparation_validate_input_path <- function(path, config_path) {
  if (!file.exists(path)) {
    .preparation_abort(config_path, "input CSV does not exist: %s", path)
  }
  info <- file.info(path)
  if (isTRUE(info$isdir)) {
    .preparation_abort(config_path, "input path is a directory: %s", path)
  }
  if (file.access(path, mode = 4L) != 0L) {
    .preparation_abort(config_path, "input CSV is not readable: %s", path)
  }
  invisible(path)
}

load_preparation_config <- function(config_path) {
  if (
    !is.character(config_path) ||
      length(config_path) != 1L ||
      is.na(config_path) ||
      !nzchar(trimws(config_path))
  ) {
    stop("Preparation config path must be one nonempty string.", call. = FALSE)
  }
  if (!file.exists(config_path) || isTRUE(file.info(config_path)$isdir)) {
    stop(
      sprintf("Preparation config file does not exist: %s", config_path),
      call. = FALSE
    )
  }
  if (file.access(config_path, mode = 4L) != 0L) {
    stop(
      sprintf("Preparation config file is not readable: %s", config_path),
      call. = FALSE
    )
  }
  if (!requireNamespace("yaml", quietly = TRUE)) {
    stop("Package 'yaml' is required to load preparation config.", call. = FALSE)
  }

  config_path <- normalizePath(config_path, winslash = "/", mustWork = TRUE)
  config_directory <- dirname(config_path)
  config <- tryCatch(
    yaml::read_yaml(
      config_path,
      eval.expr = FALSE,
      handlers = list(seq = .preparation_yaml_sequence)
    ),
    error = function(error) {
      .preparation_abort(
        config_path,
        "YAML could not be parsed: %s",
        conditionMessage(error)
      )
    }
  )

  if (
    !is.list(config) ||
      inherits(config, "yaml_sequence") ||
      is.null(names(config)) ||
      any(!nzchar(names(config)))
  ) {
    .preparation_abort(config_path, "top level must be a YAML mapping.")
  }

  unknown <- setdiff(names(config), PREPARATION_CONFIG_KEYS)
  if (length(unknown) > 0L) {
    .preparation_abort(
      config_path,
      "unknown field(s): %s",
      paste(unknown, collapse = ", ")
    )
  }

  missing_required <- setdiff(c("input_paths", "output_path"), names(config))
  if (length(missing_required) > 0L) {
    .preparation_abort(
      config_path,
      "missing required field(s): %s",
      paste(missing_required, collapse = ", ")
    )
  }

  input_paths <- .preparation_string_sequence(
    config$input_paths,
    "input_paths",
    config_path
  )
  output_path <- .preparation_scalar_string(
    config$output_path,
    "output_path",
    config_path
  )
  top_share <- if ("top_share" %in% names(config)) {
    .preparation_probability(config$top_share, "top_share", config_path)
  } else {
    0.08
  }
  probability_threshold <- if ("probability_threshold" %in% names(config)) {
    .preparation_probability(
      config$probability_threshold,
      "probability_threshold",
      config_path
    )
  } else {
    0.99
  }
  ranking_group_variables <- if (
    "ranking_group_variables" %in% names(config)
  ) {
    .preparation_string_sequence(
      config$ranking_group_variables,
      "ranking_group_variables",
      config_path
    )
  } else {
    c("city", "year")
  }
  scenario_covariates <- if ("scenario_covariates" %in% names(config)) {
    .preparation_string_sequence(
      config$scenario_covariates,
      "scenario_covariates",
      config_path,
      allow_empty = TRUE
    )
  } else {
    character()
  }
  candidate_covariates <- if ("candidate_covariates" %in% names(config)) {
    .preparation_string_sequence(
      config$candidate_covariates,
      "candidate_covariates",
      config_path,
      allow_empty = TRUE
    )
  } else {
    character()
  }

  configured_paths <- c(input_paths, output_path)
  expanded_paths <- path.expand(configured_paths)
  unresolved_home <- startsWith(configured_paths, "~") &
    startsWith(expanded_paths, "~")
  if (any(unresolved_home)) {
    .preparation_abort(
      config_path,
      "home-directory shorthand cannot be expanded in path '%s'.",
      configured_paths[which(unresolved_home)[1L]]
    )
  }

  .preparation_validate_names(
    ranking_group_variables,
    "ranking_group_variables",
    config_path
  )
  .preparation_validate_names(
    scenario_covariates,
    "scenario_covariates",
    config_path,
    reject_reserved = TRUE
  )
  .preparation_validate_names(
    candidate_covariates,
    "candidate_covariates",
    config_path,
    reject_reserved = TRUE
  )

  overlapping_covariates <- intersect(scenario_covariates, candidate_covariates)
  if (length(overlapping_covariates) > 0L) {
    .preparation_abort(
      config_path,
      "scenario and candidate covariates overlap at '%s'.",
      overlapping_covariates[1L]
    )
  }

  available_ranking_columns <- c(
    PREPARATION_PRE_RANKING_COLUMNS,
    scenario_covariates,
    candidate_covariates
  )
  unavailable_ranking_columns <- setdiff(
    ranking_group_variables,
    available_ranking_columns
  )
  if (length(unavailable_ranking_columns) > 0L) {
    .preparation_abort(
      config_path,
      "ranking field '%s' is not available before ranking.",
      unavailable_ranking_columns[1L]
    )
  }

  if (any(tolower(tools::file_ext(input_paths)) != "csv")) {
    .preparation_abort(config_path, "every input path must end in '.csv'.")
  }
  if (tolower(tools::file_ext(output_path)) != "csv") {
    .preparation_abort(config_path, "'output_path' must end in '.csv'.")
  }

  resolved_input_paths <- vapply(
    input_paths,
    .preparation_resolve_path,
    character(1),
    config_directory = config_directory,
    must_work = FALSE
  )
  input_labels <- vapply(
    input_paths,
    .preparation_path_label,
    character(1)
  )
  for (path in resolved_input_paths) {
    .preparation_validate_input_path(path, config_path)
  }

  duplicate_input <- duplicated(input_labels)
  if (any(duplicate_input)) {
    .preparation_abort(
      config_path,
      "'input_paths' resolves duplicate source label '%s'.",
      input_labels[which(duplicate_input)[1L]]
    )
  }
  duplicate_resolved_input <- duplicated(resolved_input_paths)
  if (any(duplicate_resolved_input)) {
    .preparation_abort(
      config_path,
      "'input_paths' refers to the same file more than once: %s",
      resolved_input_paths[which(duplicate_resolved_input)[1L]]
    )
  }

  resolved_output_path <- .preparation_resolve_path(
    output_path,
    config_directory,
    must_work = FALSE
  )
  output_label <- .preparation_path_label(output_path)
  if (
    file.exists(resolved_output_path) &&
      isTRUE(file.info(resolved_output_path)$isdir)
  ) {
    .preparation_abort(
      config_path,
      "'output_path' is a directory: %s",
      resolved_output_path
    )
  }
  if (resolved_output_path %in% resolved_input_paths) {
    .preparation_abort(
      config_path,
      "'output_path' must be distinct from every input path."
    )
  }

  structure(
    list(
      config_path = config_path,
      config_directory = config_directory,
      input_paths = unname(input_labels),
      resolved_input_paths = unname(resolved_input_paths),
      output_path = unname(output_label),
      resolved_output_path = unname(resolved_output_path),
      top_share = top_share,
      probability_threshold = probability_threshold,
      ranking_group_variables = ranking_group_variables,
      scenario_covariates = scenario_covariates,
      candidate_covariates = candidate_covariates
    ),
    class = c("preparation_config", "list")
  )
}
