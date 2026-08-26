find_regression_project_root <- function(start = getwd()) {
  current <- normalizePath(start, winslash = "/", mustWork = TRUE)
  repeat {
    if (
      file.exists(file.path(current, "renv.lock")) &&
        dir.exists(file.path(current, "R", "regression"))
    ) {
      return(current)
    }
    parent <- dirname(current)
    if (identical(parent, current)) {
      stop("Could not locate the LLM AuditKit repository root.", call. = FALSE)
    }
    current <- parent
  }
}

REGRESSION_PROJECT_ROOT <- find_regression_project_root()

source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "preparation_config.R"),
  local = TRUE
)
source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "experiment_results.R"),
  local = TRUE
)
source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "preparation.R"),
  local = TRUE
)
source(
  file.path(
    REGRESSION_PROJECT_ROOT,
    "R",
    "regression",
    "preparation_runner.R"
  ),
  local = TRUE
)
source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "regression_config.R"),
  local = TRUE
)
source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "regression_data.R"),
  local = TRUE
)
source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "estimation.R"),
  local = TRUE
)
source(
  file.path(
    REGRESSION_PROJECT_ROOT,
    "R",
    "regression",
    "regression_runner.R"
  ),
  local = TRUE
)

regression_fixture <- function(...) {
  file.path(
    REGRESSION_PROJECT_ROOT,
    "tests",
    "r",
    "fixtures",
    "regression",
    ...
  )
}

yaml_quote <- function(value) {
  sprintf("'%s'", gsub("'", "''", value, fixed = TRUE))
}

write_test_config <- function(
  input_paths,
  output_path,
  extra_lines = character(),
  input_as_sequence = TRUE
) {
  directory <- tempfile("regression-config-")
  dir.create(directory, recursive = TRUE)
  config_path <- file.path(directory, "preparation.yaml")
  input_lines <- if (input_as_sequence) {
    c("input_paths:", paste0("  - ", vapply(input_paths, yaml_quote, character(1))))
  } else {
    sprintf("input_paths: %s", yaml_quote(input_paths[[1L]]))
  }
  writeLines(
    c(
      input_lines,
      sprintf("output_path: %s", yaml_quote(output_path)),
      extra_lines
    ),
    config_path,
    useBytes = TRUE
  )
  config_path
}

write_raw_csv <- function(directory, name, header, rows = character()) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  path <- file.path(directory, name)
  writeLines(c(header, rows), path, useBytes = TRUE)
  path
}

minimal_raw_header <- paste(
  c(
    "scenario_id",
    "persona_id",
    "model_config_id",
    "result_status",
    "candidate_count",
    "city",
    "year"
  ),
  collapse = ","
)
