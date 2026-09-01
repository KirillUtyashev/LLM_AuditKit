#' Plot tidy regression results in the current R session
#'
#' `results` may be the object returned by `estimate_regressions()` or
#' `run_regressions()`, an independently constructed table satisfying the same
#' public result schema, a nonempty list of such tables, or one or more result
#' CSV paths. Inputs are validated and in-memory objects are never modified. The
#' returned patchwork object is printed automatically at the R console and can
#' also be further composed or saved by the caller.
#'
#' @param results One tidy regression-results data.frame, a nonempty list of
#'   them, or a nonempty character vector of result CSV paths.
#' @param config A validated `regression_plot_config` (a `render_config` is also
#'   accepted).
#' @return A patchwork plot object.
plot_regression_results <- function(results, config) {
  if (missing(results)) {
    stop("'results' must be supplied.", call. = FALSE)
  }
  if (missing(config)) {
    stop("'config' must be supplied.", call. = FALSE)
  }
  prepared <- prepare_regression_plot_data(results = results, config = config)
  build_regression_plot(prepared)
}
