script_argument <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
if (length(script_argument) != 1L) {
  stop("Could not determine the rendering script path.", call. = FALSE)
}
script_path <- normalizePath(
  sub("^--file=", "", script_argument[[1L]]), winslash = "/", mustWork = TRUE
)
project_root <- dirname(dirname(script_path))

Sys.setenv(RENV_PROJECT = project_root)
source(file.path(project_root, "renv", "activate.R"))
source(file.path(project_root, "R", "regression", "regression_config.R"))
source(file.path(project_root, "R", "regression", "render_config.R"))
source(file.path(project_root, "R", "regression", "render_data.R"))
source(file.path(project_root, "R", "regression", "paper_plot.R"))
source(file.path(project_root, "R", "regression", "render_runner.R"))

exit_status <- tryCatch({
  config_path <- .render_parse_cli_args(commandArgs(trailingOnly = TRUE))
  render_regression_plot(config_path)
  0L
}, error = function(error) {
  message("Error: ", conditionMessage(error))
  1L
})
quit(save = "no", status = exit_status)
