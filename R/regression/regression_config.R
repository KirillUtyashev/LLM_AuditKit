REGRESSION_CONFIG_KEYS <- c(
  "data_path",
  "dataset_id",
  "model_id",
  "outcome_variable",
  "explanatory_variables",
  "control_variables",
  "fixed_effects",
  "cluster_variables",
  "estimation_group_variables",
  "output_directory"
)

REGRESSION_RESULT_CORE_COLUMNS <- c(
  "dataset_id",
  "audit_id",
  "model_id",
  "estimator",
  "estimator_version",
  "inference_contract_id",
  "outcome_variable",
  "term",
  "estimate",
  "std_error",
  "statistic",
  "p_value",
  "n_input",
  "n_complete",
  "n_used",
  "n_missing_dropped",
  "n_estimator_dropped",
  "n_dropped",
  "confidence_level",
  "conf_low",
  "conf_high",
  "vcov_type",
  "explanatory_variables",
  "control_variables",
  "fixed_effects",
  "cluster_variables",
  "estimation_group_variables",
  "cluster_counts",
  "preparation_top_share",
  "preparation_probability_threshold",
  "preparation_ranking_group_variables",
  "preparation_scenario_covariates",
  "preparation_candidate_covariates"
)

.regression_config_abort <- function(config_path, format, ...) {
  message <- sprintf(format, ...)
  stop(
    sprintf("Invalid regression config '%s': %s", config_path, message),
    call. = FALSE
  )
}

.regression_config_yaml_sequence <- function(value) {
  structure(value, class = c("yaml_sequence", "list"))
}

.regression_config_scalar_string <- function(value, field, config_path) {
  if (
    inherits(value, "yaml_sequence") ||
      !is.character(value) ||
      length(value) != 1L ||
      is.na(value) ||
      !nzchar(trimws(value))
  ) {
    .regression_config_abort(
      config_path,
      "'%s' must be one nonempty string.",
      field
    )
  }
  value
}

.regression_config_string_sequence <- function(
  value,
  field,
  config_path,
  allow_empty
) {
  if (!inherits(value, "yaml_sequence")) {
    .regression_config_abort(
      config_path,
      "'%s' must be a YAML list of strings.",
      field
    )
  }
  if (!allow_empty && length(value) == 0L) {
    .regression_config_abort(config_path, "'%s' must not be empty.", field)
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
        .regression_config_abort(
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
    .regression_config_abort(
      config_path,
      "'%s' contains duplicate value '%s'.",
      field,
      values[which(duplicate)[1L]]
    )
  }
  values
}

.regression_config_validate_variable_names <- function(
  values,
  field,
  config_path
) {
  invalid <- !grepl("^[A-Za-z][A-Za-z0-9_]*$", values) |
    make.names(values) != values
  if (any(invalid)) {
    .regression_config_abort(
      config_path,
      "'%s' contains invalid column name '%s'.",
      field,
      values[which(invalid)[1L]]
    )
  }
  invisible(values)
}

.regression_config_is_absolute_path <- function(path) {
  startsWith(path, "~") ||
    grepl("^/", path) ||
    grepl("^[A-Za-z]:[/\\\\]", path) ||
    grepl("^\\\\\\\\", path)
}

.regression_config_normalize_lexical_path <- function(path) {
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

.regression_config_path_label <- function(path) {
  if (startsWith(path, "~")) {
    path <- path.expand(path)
  }
  .regression_config_normalize_lexical_path(path)
}

.regression_config_resolve_path <- function(path, config_directory) {
  expanded <- path.expand(path)
  candidate <- if (.regression_config_is_absolute_path(path)) {
    expanded
  } else {
    file.path(config_directory, expanded)
  }
  normalizePath(candidate, winslash = "/", mustWork = FALSE)
}

load_regression_config <- function(config_path) {
  if (
    !is.character(config_path) ||
      length(config_path) != 1L ||
      is.na(config_path) ||
      !nzchar(trimws(config_path))
  ) {
    stop("Regression config path must be one nonempty string.", call. = FALSE)
  }
  if (!file.exists(config_path) || isTRUE(file.info(config_path)$isdir)) {
    stop(
      sprintf("Regression config file does not exist: %s", config_path),
      call. = FALSE
    )
  }
  if (file.access(config_path, mode = 4L) != 0L) {
    stop(
      sprintf("Regression config file is not readable: %s", config_path),
      call. = FALSE
    )
  }
  if (!requireNamespace("yaml", quietly = TRUE)) {
    stop("Package 'yaml' is required to load regression config.", call. = FALSE)
  }

  config_path <- normalizePath(config_path, winslash = "/", mustWork = TRUE)
  config_directory <- dirname(config_path)
  config <- tryCatch(
    yaml::read_yaml(
      config_path,
      eval.expr = FALSE,
      handlers = list(seq = .regression_config_yaml_sequence)
    ),
    error = function(error) {
      .regression_config_abort(
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
    .regression_config_abort(config_path, "top level must be a YAML mapping.")
  }

  unknown <- setdiff(names(config), REGRESSION_CONFIG_KEYS)
  if (length(unknown) > 0L) {
    .regression_config_abort(
      config_path,
      "unknown field(s): %s",
      paste(unknown, collapse = ", ")
    )
  }
  required <- setdiff(
    REGRESSION_CONFIG_KEYS,
    "estimation_group_variables"
  )
  missing_required <- setdiff(required, names(config))
  if (length(missing_required) > 0L) {
    .regression_config_abort(
      config_path,
      "missing required field(s): %s",
      paste(missing_required, collapse = ", ")
    )
  }

  data_path <- .regression_config_scalar_string(
    config$data_path,
    "data_path",
    config_path
  )
  dataset_id <- .regression_config_scalar_string(
    config$dataset_id,
    "dataset_id",
    config_path
  )
  model_id <- .regression_config_scalar_string(
    config$model_id,
    "model_id",
    config_path
  )
  outcome_variable <- .regression_config_scalar_string(
    config$outcome_variable,
    "outcome_variable",
    config_path
  )
  explanatory_variables <- .regression_config_string_sequence(
    config$explanatory_variables,
    "explanatory_variables",
    config_path,
    allow_empty = FALSE
  )
  control_variables <- .regression_config_string_sequence(
    config$control_variables,
    "control_variables",
    config_path,
    allow_empty = TRUE
  )
  fixed_effects <- .regression_config_string_sequence(
    config$fixed_effects,
    "fixed_effects",
    config_path,
    allow_empty = TRUE
  )
  cluster_variables <- .regression_config_string_sequence(
    config$cluster_variables,
    "cluster_variables",
    config_path,
    allow_empty = TRUE
  )
  estimation_group_variables <- if (
    "estimation_group_variables" %in% names(config)
  ) {
    .regression_config_string_sequence(
      config$estimation_group_variables,
      "estimation_group_variables",
      config_path,
      allow_empty = TRUE
    )
  } else {
    character()
  }
  output_directory <- .regression_config_scalar_string(
    config$output_directory,
    "output_directory",
    config_path
  )

  variable_fields <- list(
    outcome_variable = outcome_variable,
    explanatory_variables = explanatory_variables,
    control_variables = control_variables,
    fixed_effects = fixed_effects,
    cluster_variables = cluster_variables,
    estimation_group_variables = estimation_group_variables
  )
  for (field in names(variable_fields)) {
    .regression_config_validate_variable_names(
      variable_fields[[field]],
      field,
      config_path
    )
  }

  audit_roles <- vapply(
    variable_fields,
    function(values) "audit_id" %in% values,
    logical(1)
  )
  if (any(audit_roles)) {
    .regression_config_abort(
      config_path,
      "'audit_id' is provenance and cannot be configured in '%s'.",
      names(audit_roles)[which(audit_roles)[[1L]]]
    )
  }

  right_hand_side <- c(explanatory_variables, control_variables)
  if (outcome_variable %in% right_hand_side) {
    .regression_config_abort(
      config_path,
      "outcome variable '%s' cannot also appear on the right-hand side.",
      outcome_variable
    )
  }
  explanatory_control_overlap <- intersect(
    explanatory_variables,
    control_variables
  )
  if (length(explanatory_control_overlap) > 0L) {
    .regression_config_abort(
      config_path,
      "explanatory and control variables overlap at '%s'.",
      explanatory_control_overlap[1L]
    )
  }
  reserved_group <- estimation_group_variables %in%
    REGRESSION_RESULT_CORE_COLUMNS
  if (any(reserved_group)) {
    .regression_config_abort(
      config_path,
      "estimation group variable '%s' collides with a reserved result column.",
      estimation_group_variables[which(reserved_group)[1L]]
    )
  }

  configured_paths <- c(data_path, output_directory)
  expanded_paths <- path.expand(configured_paths)
  unresolved_home <- startsWith(configured_paths, "~") &
    startsWith(expanded_paths, "~")
  if (any(unresolved_home)) {
    .regression_config_abort(
      config_path,
      "home-directory shorthand cannot be expanded in path '%s'.",
      configured_paths[which(unresolved_home)[1L]]
    )
  }
  if (tolower(tools::file_ext(data_path)) != "csv") {
    .regression_config_abort(config_path, "'data_path' must end in '.csv'.")
  }

  resolved_data_path <- .regression_config_resolve_path(
    data_path,
    config_directory
  )
  if (!file.exists(resolved_data_path)) {
    .regression_config_abort(
      config_path,
      "data CSV does not exist: %s",
      resolved_data_path
    )
  }
  if (isTRUE(file.info(resolved_data_path)$isdir)) {
    .regression_config_abort(
      config_path,
      "data path is a directory: %s",
      resolved_data_path
    )
  }
  if (file.access(resolved_data_path, mode = 4L) != 0L) {
    .regression_config_abort(
      config_path,
      "data CSV is not readable: %s",
      resolved_data_path
    )
  }

  resolved_output_directory <- .regression_config_resolve_path(
    output_directory,
    config_directory
  )
  if (
    file.exists(resolved_output_directory) &&
      !isTRUE(file.info(resolved_output_directory)$isdir)
  ) {
    .regression_config_abort(
      config_path,
      "'output_directory' is an existing file: %s",
      resolved_output_directory
    )
  }
  resolved_output_path <- normalizePath(
    file.path(resolved_output_directory, "regression_results.csv"),
    winslash = "/",
    mustWork = FALSE
  )
  if (
    file.exists(resolved_output_path) &&
      isTRUE(file.info(resolved_output_path)$isdir)
  ) {
    .regression_config_abort(
      config_path,
      "computed regression result path is a directory: %s",
      resolved_output_path
    )
  }
  if (identical(resolved_data_path, resolved_output_path)) {
    .regression_config_abort(
      config_path,
      "computed 'regression_results.csv' must be distinct from 'data_path'."
    )
  }

  structure(
    list(
      config_path = config_path,
      config_directory = config_directory,
      data_path = .regression_config_path_label(data_path),
      resolved_data_path = resolved_data_path,
      dataset_id = dataset_id,
      model_id = model_id,
      outcome_variable = outcome_variable,
      explanatory_variables = explanatory_variables,
      control_variables = control_variables,
      fixed_effects = fixed_effects,
      cluster_variables = cluster_variables,
      estimation_group_variables = estimation_group_variables,
      output_directory = .regression_config_path_label(output_directory),
      resolved_output_directory = resolved_output_directory,
      resolved_output_path = resolved_output_path
    ),
    class = c("regression_config", "list")
  )
}

.regression_as_config <- function(config) {
  if (is.character(config) && length(config) == 1L && !is.na(config)) {
    config <- load_regression_config(config)
  }
  if (!inherits(config, "regression_config")) {
    stop(
      "'config' must be a regression_config or one YAML config path.",
      call. = FALSE
    )
  }
  config
}
