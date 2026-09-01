.plot_api_config <- function(...) {
  arguments <- list(
    term = "black",
    period_variable = "period",
    outcome_variable = "pick_top",
    panel_variable = "audit_id"
  )
  changes <- list(...)
  if (length(changes) > 0L) {
    arguments[names(changes)] <- changes
  }
  do.call(regression_plot_config, arguments)
}

.plot_api_fixture <- function() {
  results <- .render_validate_result_file(
    .render_read_csv(
      regression_fixture("render_results_synthetic.csv"),
      "synthetic fixture"
    ),
    "synthetic fixture"
  )
  results$outcome_variable <- "pick_top"
  results
}

.plot_api_render_path <- function(results) {
  directory <- tempfile("plot-api-")
  dir.create(directory)
  utils::write.table(
    results,
    file.path(directory, "results.csv"),
    sep = ",", row.names = FALSE, quote = TRUE, qmethod = "double", na = ""
  )
  path <- file.path(directory, "render.yaml")
  writeLines(c(
    "results_paths: [results.csv]",
    "output_path: figure.png",
    "term: black",
    "outcome_variable: pick_top",
    "period_variable: period",
    "panel_variable: audit_id"
  ), path)
  path
}

testthat::test_that("in-memory tables and equivalent CSV inputs prepare identically", {
  results <- .plot_api_fixture()
  class(results) <- c("regression_results", class(results))
  attr(results, "regression_fit_count") <- 24L
  original <- unserialize(serialize(results, NULL))

  from_object <- prepare_regression_plot_data(
    results,
    .plot_api_config()
  )
  render_path <- .plot_api_render_path(results)
  render_config <- load_render_config(render_path)
  from_files <- prepare_regression_plot_data(render_path)
  from_paths <- prepare_regression_plot_data(
    render_config$resolved_results_paths,
    .plot_api_config()
  )
  pieces <- split(results, results$audit_id)
  pieces <- pieces[c("audit_d", "audit_b", "audit_a", "audit_c")]
  names(pieces) <- c("unrelated_one", "unrelated_two", "unrelated_three", "unrelated_four")
  from_list <- prepare_regression_plot_data(
    pieces,
    .plot_api_config()
  )

  testthat::expect_identical(from_object$data, from_files$data)
  testthat::expect_identical(from_paths$data, from_files$data)
  testthat::expect_identical(from_list$data, from_files$data)
  testthat::expect_identical(from_object$period_order, from_files$period_order)
  testthat::expect_identical(from_object$panel_order, from_files$panel_order)
  testthat::expect_identical(results, original)
})

testthat::test_that("separate audits plot as panels with city-year estimates", {
  source <- .render_validate_result_file(
    .render_read_csv(
      regression_fixture("render_results_synthetic.csv"),
      "synthetic multi-audit fixture"
    ),
    "synthetic multi-audit fixture"
  )
  cities <- c("Birmingham", "Boston", "Chicago")
  audit_results <- lapply(split(source, source$audit_id), function(audit) {
    city_results <- do.call(rbind, lapply(cities, function(city) {
      rows <- audit
      rows$city <- city
      rows
    }))
    city_results$year <- city_results$period
    city_results$estimation_group_variables <- "city|year"
    city_results$model_config_id <- NULL
    city_results$period <- NULL
    city_results <- city_results[c(
      REGRESSION_RESULT_CORE_COLUMNS,
      "city",
      "year"
    )]
    row.names(city_results) <- NULL
    city_results
  })
  original <- unserialize(serialize(audit_results, NULL))
  outcomes <- c(
    audit_a = "pick_top",
    audit_b = "pick_threshold",
    audit_c = "pick_threshold",
    audit_d = "pick_threshold"
  )
  config <- regression_plot_config(
    term = "black",
    period_variable = "year",
    series_variable = "city",
    panel_variable = "audit_id",
    outcome_by_panel = outcomes,
    series_order = cities,
    panel_order = names(outcomes)
  )

  prepared <- prepare_regression_plot_data(audit_results, config)
  directory <- tempfile("multi-audit-paths-")
  dir.create(directory)
  paths <- file.path(directory, paste0(names(audit_results), ".csv"))
  for (index in seq_along(paths)) {
    utils::write.table(
      audit_results[[index]],
      paths[[index]],
      sep = ",",
      row.names = FALSE,
      quote = TRUE,
      qmethod = "double",
      na = ""
    )
  }
  from_paths <- prepare_regression_plot_data(paths, config)

  testthat::expect_identical(prepared$panel_order, names(outcomes))
  testthat::expect_identical(prepared$series_order, cities)
  testthat::expect_identical(nrow(prepared$data), 72L)
  panel_counts <- table(prepared$data$.plot_panel)
  testthat::expect_identical(names(panel_counts), names(outcomes))
  testthat::expect_identical(as.integer(panel_counts), rep(18L, 4L))
  testthat::expect_identical(
    unique(prepared$data$outcome_variable),
    c("pick_top", "pick_threshold")
  )
  testthat::expect_identical(from_paths$data, prepared$data)
  for (audit_id in names(outcomes)) {
    rows <- prepared$data$audit_id == audit_id
    testthat::expect_identical(
      unique(prepared$data$outcome_variable[rows]),
      unname(outcomes[[audit_id]])
    )
    testthat::expect_length(unique(prepared$data$dataset_id[rows]), 1L)
  }
  testthat::expect_s3_class(
    plot_regression_results(audit_results, config),
    "patchwork"
  )
  testthat::expect_identical(audit_results, original)

  missing_term <- audit_results
  missing_term[["audit_d"]]$term <- "unavailable_term"
  testthat::expect_error(
    prepare_regression_plot_data(missing_term, config),
    "term and confidence-level selection.*audit_id='audit_d'"
  )

  same_audit_sources <- list(
    slice_a = audit_results[["audit_a"]],
    slice_b = audit_results[["audit_a"]]
  )
  same_audit_sources$slice_b$dataset_id <- "second_dataset"
  same_audit_sources$slice_b$term <- "unavailable_term"
  dataset_config <- regression_plot_config(
    term = "black",
    outcome_variable = "pick_top",
    period_variable = "year",
    series_variable = "city",
    panel_variable = "dataset_id",
    series_order = cities
  )
  testthat::expect_error(
    prepare_regression_plot_data(same_audit_sources, dataset_config),
    "term and confidence-level selection.*audit_id='audit_a', dataset_id='second_dataset'"
  )

  mixed_dataset <- audit_results
  changed <- mixed_dataset[["audit_a"]]$year == "1970" &
    mixed_dataset[["audit_a"]]$city == "Birmingham"
  mixed_dataset[["audit_a"]]$dataset_id[changed] <- "other_slice"
  testthat::expect_error(
    prepare_regression_plot_data(mixed_dataset, config),
    "incompatible 'dataset_id' within panel 'audit_a'"
  )
})

testthat::test_that("one-panel in-memory plots do not require a panel column role", {
  results <- .plot_api_fixture()
  results <- results[results$model_config_id == "model_a", , drop = FALSE]
  prepared <- prepare_regression_plot_data(
    results,
    .plot_api_config(panel_variable = NULL)
  )

  testthat::expect_identical(prepared$panel_order, ".single_panel")
  testthat::expect_identical(unname(prepared$panel_labels), "pick_top")
  testthat::expect_identical(unique(prepared$data$.plot_panel), ".single_panel")
  testthat::expect_identical(nrow(prepared$data), 6L)

  absent_panel_source <- results[setdiff(names(results), "model_config_id")]
  absent_panel_source$estimation_group_variables <- "period"
  testthat::expect_identical(
    nrow(prepare_regression_plot_data(
      absent_panel_source,
      .plot_api_config(panel_variable = NULL)
    )$data),
    6L
  )
})

testthat::test_that("outcome and coefficient selections are explicit in memory", {
  top <- .plot_api_fixture()
  threshold <- top
  threshold$outcome_variable <- "pick_threshold"
  combined_outcomes <- rbind(top, threshold)

  selected <- prepare_regression_plot_data(
    combined_outcomes,
    .plot_api_config(outcome_variable = "pick_threshold")
  )
  testthat::expect_identical(
    unique(selected$data$outcome_variable),
    "pick_threshold"
  )
  testthat::expect_error(
    prepare_regression_plot_data(
      combined_outcomes,
      .plot_api_config(outcome_variable = "missing")
    ),
    "outcome selection.*audit_id='audit_a'"
  )

  second_term <- top
  second_term$term <- "high"
  selected_term <- prepare_regression_plot_data(
    rbind(top, second_term),
    .plot_api_config(term = "high")
  )
  testthat::expect_identical(unique(selected_term$data$term), "high")
  testthat::expect_equal(
    selected_term$data$estimate,
    second_term$estimate[second_term$confidence_level == .95]
  )
})

testthat::test_that("in-memory lists are validated as one combined result set", {
  results <- .plot_api_fixture()
  levels <- lapply(c(.90, .95, .99), function(level) {
    results[results$confidence_level == level, , drop = FALSE]
  })
  combined <- validate_regression_results(levels)
  testthat::expect_identical(nrow(combined), 72L)

  inconsistent <- levels
  inconsistent[[2L]]$p_value[[1L]] <- .123
  testthat::expect_error(
    validate_regression_results(inconsistent),
    "statistics or metadata disagree across saved intervals"
  )
  testthat::expect_error(
    validate_regression_results(list(results, results)),
    "duplicate saved coefficient/interval keys"
  )
})

testthat::test_that("malformed in-memory sources and missing plot roles fail clearly", {
  results <- .plot_api_fixture()
  testthat::expect_error(validate_regression_results(list()), "must not be an empty list")
  testthat::expect_error(
    validate_regression_results(list(results, matrix(1))),
    "element 2 must be.*data.frame"
  )
  testthat::expect_error(
    validate_regression_results(results[FALSE, ]),
    "at least one result row"
  )
  missing_core <- results[setdiff(names(results), "std_error")]
  testthat::expect_error(
    validate_regression_results(missing_core),
    "missing required result column.*std_error"
  )
  list_column <- results
  list_column$dataset_id <- as.list(list_column$dataset_id)
  testthat::expect_error(
    validate_regression_results(list_column),
    "column 'dataset_id' must be one atomic vector"
  )

  testthat::expect_error(
    prepare_regression_plot_data(results, .plot_api_config(term = "missing")),
    "term and confidence-level selection.*audit_id='audit_a'"
  )
  for (role in c("period_variable", "series_variable", "panel_variable")) {
    changes <- stats::setNames(list("missing"), role)
    testthat::expect_error(
      prepare_regression_plot_data(results, do.call(.plot_api_config, changes)),
      "missing configured column 'missing'",
      info = role
    )
  }
  testthat::expect_error(
    prepare_regression_plot_data(results = results),
    "'config' must be supplied"
  )
  testthat::expect_error(
    prepare_regression_plot_data(config = .plot_api_config()),
    "'results' must be supplied"
  )
  testthat::expect_error(
    prepare_regression_plot_data(character(), .plot_api_config()),
    "results_paths.*nonempty character vector"
  )
  testthat::expect_error(
    prepare_regression_plot_data("missing.csv", .plot_api_config()),
    "does not exist"
  )
  wrong_extension <- tempfile(fileext = ".txt")
  writeLines("not,csv", wrong_extension)
  testthat::expect_error(
    prepare_regression_plot_data(wrong_extension, .plot_api_config()),
    "must end in '.csv'",
    fixed = TRUE
  )
})

testthat::test_that("interactive plotting returns a composable plot object", {
  results <- .plot_api_fixture()
  plot <- plot_regression_results(results, .plot_api_config())
  testthat::expect_s3_class(plot, "patchwork")
  render_config <- load_render_config(.plot_api_render_path(results))
  testthat::expect_s3_class(
    plot_regression_results(
      render_config$resolved_results_paths,
      .plot_api_config()
    ),
    "patchwork"
  )
  testthat::expect_error(plot_regression_results(config = .plot_api_config()),
    "'results' must be supplied")
  testthat::expect_error(plot_regression_results(results),
    "'config' must be supplied")
})

testthat::test_that("one public loader supports a fresh interactive workflow", {
  directory <- tempfile("regression-interactive-loader-")
  dir.create(directory)
  config_path <- file.path(directory, "regression.yaml")
  writeLines(c(
    paste0(
      "data_path: ",
      yaml_quote(regression_fixture("regression_ready_known.csv"))
    ),
    "dataset_id: loader_fixture",
    "model_id: loader_multi_iv",
    "outcome_variable: pick_top",
    "explanatory_variables: [black, high]",
    "control_variables: []",
    "fixed_effects: [position_fe]",
    "cluster_variables: []",
    "estimation_group_variables: [period]",
    "output_directory: unused_output"
  ), config_path, useBytes = TRUE)
  caller_directory <- file.path(directory, "caller")
  dir.create(caller_directory)
  previous <- setwd(caller_directory)
  on.exit(setwd(previous), add = TRUE)

  quoted <- function(value) encodeString(value, quote = '"')
  code <- paste(
    paste0("project <- ", quoted(REGRESSION_PROJECT_ROOT)),
    "Sys.unsetenv('RENV_PROJECT')",
    "source(file.path(project, 'R', 'regression', 'load.R'))",
    paste0(
      "lock <- renv::lockfile_read(file.path(project, 'renv.lock')); ",
      "stopifnot(normalizePath(Sys.getenv('RENV_PROJECT')) == ",
      "normalizePath(project), ",
      "as.character(packageVersion('fixest')) == lock$Packages$fixest$Version, ",
      "as.character(packageVersion('ggplot2')) == lock$Packages$ggplot2$Version, ",
      "as.character(packageVersion('patchwork')) == lock$Packages$patchwork$Version)"
    ),
    paste0("results <- estimate_regressions(", quoted(config_path), ")"),
    paste0(
      "config <- regression_plot_config(term = 'high', ",
      "outcome_variable = 'pick_top', period_variable = 'period')"
    ),
    "plot <- plot_regression_results(results, config)",
    paste0(
      "stopifnot(inherits(results, 'regression_results'), nrow(results) == 12L, ",
      "setequal(unique(results$term), c('black', 'high')), ",
      "inherits(plot, 'patchwork'))"
    ),
    "cat('Interactive regression workflow loaded successfully.\\n')",
    sep = "; "
  )
  output <- system2(
    file.path(R.home("bin"), "Rscript"),
    c("--vanilla", "-e", shQuote(code)),
    stdout = TRUE,
    stderr = TRUE
  )
  status <- attr(output, "status", exact = TRUE)
  if (is.null(status)) {
    status <- 0L
  }
  testthat::expect_identical(status, 0L)
  testthat::expect_match(
    paste(output, collapse = "\n"),
    "Interactive regression workflow loaded successfully.",
    fixed = TRUE
  )
  testthat::expect_false(file.exists(file.path(caller_directory, "Rplots.pdf")))
})
