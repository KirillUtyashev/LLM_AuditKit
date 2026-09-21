# Public source entry point for interactive R use. The implementation modules
# remain independently sourceable by the thin command-line scripts.
.regression_loader_frame_paths <- vapply(
  sys.frames(),
  function(frame) {
    path <- frame$ofile
    if (is.null(path) || length(path) != 1L || is.na(path)) NA_character_ else path
  },
  character(1)
)
.regression_loader_candidates <- .regression_loader_frame_paths[
  !is.na(.regression_loader_frame_paths) &
    basename(.regression_loader_frame_paths) == "load.R"
]
.regression_loader_path <- if (length(.regression_loader_candidates) == 0L) {
  NULL
} else {
  tryCatch(
    normalizePath(
      tail(.regression_loader_candidates, 1L),
      winslash = "/",
      mustWork = TRUE
    ),
    error = function(error) NULL
  )
}
if (is.null(.regression_loader_path)) {
  stop(
    "Could not determine the regression loader path; use source() on R/regression/load.R.",
    call. = FALSE
  )
}

.regression_loader_environment <- environment()
.regression_loader_directory <- dirname(.regression_loader_path)
.regression_loader_project <- dirname(dirname(.regression_loader_directory))
.regression_loader_active_project <- Sys.getenv("RENV_PROJECT", unset = "")
.regression_loader_library_root <- file.path(
  .regression_loader_project, "renv", "library"
)
.regression_loader_libraries <- normalizePath(
  .libPaths(), winslash = "/", mustWork = FALSE
)
.regression_loader_is_active <-
  nzchar(.regression_loader_active_project) &&
  identical(
    normalizePath(
      .regression_loader_active_project,
      winslash = "/",
      mustWork = FALSE
    ),
    .regression_loader_project
  ) &&
  any(
    .regression_loader_libraries == .regression_loader_library_root |
      startsWith(
        .regression_loader_libraries,
        paste0(.regression_loader_library_root, "/")
      )
  )
if (!.regression_loader_is_active) {
  Sys.setenv(RENV_PROJECT = .regression_loader_project)
  source(
    file.path(.regression_loader_project, "renv", "activate.R"),
    local = .regression_loader_environment
  )
}
.regression_loader_runtime_packages <- c(
  "yaml", "fixest", "ggplot2", "patchwork"
)
.regression_loader_lock <- renv::lockfile_read(
  file.path(.regression_loader_project, "renv.lock")
)
.regression_loader_expected_versions <- vapply(
  .regression_loader_runtime_packages,
  function(package) .regression_loader_lock$Packages[[package]]$Version,
  character(1)
)
.regression_loader_loaded_runtime <- intersect(
  names(.regression_loader_expected_versions),
  loadedNamespaces()
)
.regression_loader_package <- NULL
.regression_loader_loaded_version <- NULL
.regression_loader_expected_version <- NULL
for (.regression_loader_package in .regression_loader_loaded_runtime) {
  .regression_loader_loaded_version <- as.character(
    utils::packageVersion(.regression_loader_package)
  )
  .regression_loader_expected_version <-
    .regression_loader_expected_versions[[.regression_loader_package]]
  if (!identical(
    .regression_loader_loaded_version,
    .regression_loader_expected_version
  )) {
    stop(
      sprintf(
        paste0(
          "Package '%s' version %s is already loaded, but this project ",
          "requires %s. Restart R in a clean session, then source ",
          "R/regression/load.R before loading regression packages."
        ),
        .regression_loader_package,
        .regression_loader_loaded_version,
        .regression_loader_expected_version
      ),
      call. = FALSE
    )
  }
}
.regression_loader_modules <- c(
  "preparation_config",
  "experiment_results",
  "preparation",
  "preparation_runner",
  "regression_config",
  "regression_data",
  "estimation",
  "regression_runner",
  "render_config",
  "render_data",
  "paper_plot",
  "plot_api",
  "render_runner"
)
for (.regression_loader_module in .regression_loader_modules) {
  sys.source(
    file.path(
      .regression_loader_directory,
      paste0(.regression_loader_module, ".R")
    ),
    envir = .regression_loader_environment
  )
}

rm(
  .regression_loader_active_project,
  .regression_loader_candidates,
  .regression_loader_directory,
  .regression_loader_environment,
  .regression_loader_expected_version,
  .regression_loader_expected_versions,
  .regression_loader_frame_paths,
  .regression_loader_is_active,
  .regression_loader_libraries,
  .regression_loader_library_root,
  .regression_loader_lock,
  .regression_loader_loaded_runtime,
  .regression_loader_loaded_version,
  .regression_loader_module,
  .regression_loader_modules,
  .regression_loader_package,
  .regression_loader_path,
  .regression_loader_project,
  .regression_loader_runtime_packages
)
