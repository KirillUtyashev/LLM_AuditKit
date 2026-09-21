script_argument <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
if (length(script_argument) != 1L) {
  stop("Could not determine the preparation script path.", call. = FALSE)
}
script_path <- normalizePath(
  sub("^--file=", "", script_argument[[1L]]),
  winslash = "/",
  mustWork = TRUE
)
project_root <- dirname(dirname(script_path))

Sys.setenv(RENV_PROJECT = project_root)
source(file.path(project_root, "renv", "activate.R"))
source(file.path(project_root, "R", "regression", "preparation_config.R"))
source(file.path(project_root, "R", "regression", "experiment_results.R"))
source(file.path(project_root, "R", "regression", "preparation.R"))
source(file.path(project_root, "R", "regression", "preparation_runner.R"))

exit_status <- tryCatch(
  {
    config_path <- .preparation_parse_cli_args(commandArgs(trailingOnly = TRUE))
    run_regression_preparation(config_path)
    0L
  },
  error = function(error) {
    message("Error: ", conditionMessage(error))
    1L
  }
)
quit(save = "no", status = exit_status)
