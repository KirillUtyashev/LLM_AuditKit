.render_data_test_fixture <- function(mixed_outcomes = FALSE) {
  data <- utils::read.csv(
    regression_fixture("render_results_synthetic.csv"),
    check.names = FALSE, na.strings = character(), stringsAsFactors = FALSE
  )
  if (!mixed_outcomes) {
    data$outcome_variable <- "pick_top"
  }
  data
}

.render_data_test_config <- function(
  data = .render_data_test_fixture(), settings = character(), slices = list(data)
) {
  directory <- tempfile("render-data-")
  dir.create(directory)
  inputs <- paste0("results-", seq_along(slices), ".csv")
  for (i in seq_along(slices)) {
    utils::write.table(
      slices[[i]], file.path(directory, inputs[[i]]), sep = ",",
      row.names = FALSE, quote = TRUE, qmethod = "double", na = "",
      fileEncoding = "UTF-8"
    )
  }
  values <- c(
    output_path = "figure.png", term = "black", period_variable = "period",
    panel_variable = "model_config_id"
  )
  values[names(settings)] <- settings
  path <- file.path(directory, "render.yaml")
  writeLines(c(
    "results_paths:", paste0("  - ", inputs),
    paste0(names(values), ": ", unname(values))
  ), path, useBytes = TRUE)
  path
}

testthat::test_that("saved result loading preserves its public schema and values", {
  source <- .render_data_test_fixture()
  config <- .render_data_test_config()
  actual <- load_regression_results(config)
  testthat::expect_identical(names(actual), names(source))
  testthat::expect_identical(nrow(actual), 72L)
  numeric <- c("estimate", "std_error", "statistic", "p_value", "conf_low", "conf_high")
  testthat::expect_equal(actual[numeric], source[numeric], tolerance = 1e-14)
  testthat::expect_identical(actual$period, as.character(source$period))
  testthat::expect_identical(actual$cluster_variables, rep("", 72L))
  testthat::expect_identical(actual$cluster_counts, rep("", 72L))
  testthat::expect_type(actual$n_used, "integer")

  reordered <- source[rev(seq_len(nrow(source))), rev(names(source))]
  loaded <- load_regression_results(.render_data_test_config(reordered))
  testthat::expect_identical(names(loaded), c(REGRESSION_RESULT_CORE_COLUMNS,
    "model_config_id", "period"))
  testthat::expect_equal(loaded$estimate, rev(source$estimate))

  # A researcher can save a single interval slice; a complete triplet is not required.
  sliced <- source[source$confidence_level == .95, , drop = FALSE]
  testthat::expect_identical(nrow(load_regression_results(
    .render_data_test_config(sliced))), 24L)
})

testthat::test_that("plot preparation uses the exact selected numerical results", {
  source <- .render_data_test_fixture()
  for (level in c(.9, .95, .99)) {
    prepared <- prepare_regression_plot_data(.render_data_test_config(
      settings = c(confidence_level = as.character(level))
    ))
    expected <- source[source$confidence_level == level, , drop = FALSE]
    row.names(expected) <- NULL
    testthat::expect_s3_class(prepared, "regression_plot_data")
    testthat::expect_identical(nrow(prepared$data), 24L)
    for (field in c("estimate", "std_error", "p_value", "conf_low", "conf_high")) {
      testthat::expect_equal(prepared$data[[field]], expected[[field]], tolerance = 1e-14)
    }
    testthat::expect_identical(prepared$panel_order, paste0("model_", letters[1:4]))
    testthat::expect_identical(prepared$period_order, as.character(seq(1970, 2020, 10)))
    testthat::expect_equal(prepared$data$.plot_x, rep(seq(1970, 2020, 10), 4))
    testthat::expect_identical(prepared$series_order, character())
    testthat::expect_equal(prepared$data$.plot_alpha,
      ifelse(expected$p_value < .05, 1, .3))
  }
  altered <- source
  altered$conf_low <- altered$conf_low - .004
  altered$conf_high <- altered$conf_high + .007
  prepared <- prepare_regression_plot_data(.render_data_test_config(altered))
  testthat::expect_equal(prepared$data$conf_low,
    altered$conf_low[altered$confidence_level == .95], tolerance = 1e-14)
  testthat::expect_equal(prepared$data$conf_high,
    altered$conf_high[altered$confidence_level == .95], tolerance = 1e-14)
})

testthat::test_that("mixed panel outcomes must be selected explicitly and completely", {
  data <- .render_data_test_fixture(mixed_outcomes = TRUE)
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(data)),
    "multiple outcomes.*outcome_by_panel")
  mapping <- "{model_a: pick_top, model_b: pick_threshold, model_c: pick_threshold, model_d: pick_threshold}"
  prepared <- prepare_regression_plot_data(.render_data_test_config(
    data, c(outcome_by_panel = mapping)
  ))
  testthat::expect_identical(prepared$data$outcome_variable,
    rep(c("pick_top", rep("pick_threshold", 3)), each = 6))
  for (map in c(
    "{model_a: pick_top}",
    "{model_a: pick_top, model_b: pick_threshold, model_c: pick_threshold, model_d: pick_threshold, unknown: pick_top}"
  )) {
    testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
      data, c(outcome_by_panel = map))), "cover every observed panel exactly")
  }
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
    data, c(outcome_by_panel = sub("model_a: pick_top", "model_a: missing", mapping)))),
    "selection has no saved result rows")

  # An extra, unused outcome is filtered without altering panel coverage.
  extra <- data
  extra$model_id <- paste0(extra$model_id, "_other")
  extra$outcome_variable <- "pick_raw"
  extra$fixed_effects <- "alternative_fe"
  selected <- prepare_regression_plot_data(.render_data_test_config(
    rbind(data, extra), c(outcome_by_panel = mapping)
  ))
  testthat::expect_equal(selected$data, prepared$data)
})

testthat::test_that("orders are deterministic complete permutations rather than filters", {
  data <- .render_data_test_fixture()
  data$period <- rep(rep(c("2", "10", "3", "20", "1", "30"), each = 3), 4)
  natural <- prepare_regression_plot_data(.render_data_test_config(data))
  testthat::expect_identical(natural$period_order, c("1", "2", "3", "10", "20", "30"))
  testthat::expect_equal(natural$period_positions, c(1, 2, 3, 10, 20, 30))
  order <- "['30', '20', '10', '3', '2', '1']"
  custom <- prepare_regression_plot_data(.render_data_test_config(data, c(
    period_order = order, panel_order = "[model_d, model_b, model_a, model_c]",
    panel_labels = "{model_a: Same title, model_b: Same title}"
  )))
  testthat::expect_identical(custom$period_order, c("30", "20", "10", "3", "2", "1"))
  testthat::expect_equal(custom$period_positions, seq(10, 60, 10))
  testthat::expect_identical(custom$panel_order, c("model_d", "model_b", "model_a", "model_c"))
  testthat::expect_identical(unname(custom$panel_labels[c("model_a", "model_b")]),
    rep("Same title", 2))
  testthat::expect_identical(nrow(custom$data), 24L)
  for (field in c("period_order", "panel_order")) {
    testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
      data, stats::setNames("[unknown]", field))), "complete permutation")
  }
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
    data, c(panel_labels = "{unknown: Missing}"))), "panel_labels contains unknown")

  data$period <- paste0("wave_", data$period)
  text <- prepare_regression_plot_data(.render_data_test_config(data))
  testthat::expect_identical(text$period_order,
    c("wave_1", "wave_10", "wave_2", "wave_20", "wave_3", "wave_30"))
  testthat::expect_equal(text$period_positions, seq(10, 60, 10))
})

testthat::test_that("file and row ordering cannot alter plot-ready data", {
  data <- .render_data_test_fixture()
  expected <- prepare_regression_plot_data(.render_data_test_config(data))
  slices <- list(data[37:72, ], data[36:1, ])
  actual <- prepare_regression_plot_data(.render_data_test_config(slices = slices))
  testthat::expect_identical(actual$data, expected$data)
  testthat::expect_identical(actual$period_order, expected$period_order)
  testthat::expect_identical(actual$panel_order, expected$panel_order)
})

testthat::test_that("sparse series retain their globally fixed slots", {
  left <- .render_data_test_fixture()
  left$city <- "Toronto"
  left$estimation_group_variables <- "model_config_id|period|city"
  right <- left
  right$city <- "Montreal"
  right$model_id <- paste0(right$model_id, "_montreal")
  sparse <- right[!(right$model_config_id == "model_a" & right$period == 1970), ]
  data <- rbind(left, sparse)
  settings <- c(series_variable = "city", series_order = "[Toronto, Montreal]")
  prepared <- prepare_regression_plot_data(.render_data_test_config(data, settings))
  testthat::expect_identical(nrow(prepared$data), 47L)
  testthat::expect_identical(prepared$series_order, c("Toronto", "Montreal"))
  testthat::expect_equal(prepared$data$.plot_x[prepared$data$city == "Toronto"],
    as.numeric(prepared$data$period[prepared$data$city == "Toronto"]) - 1.5)
  testthat::expect_equal(prepared$data$.plot_x[prepared$data$city == "Montreal"],
    as.numeric(prepared$data$period[prepared$data$city == "Montreal"]) + 1.5)
  reversed <- prepare_regression_plot_data(.render_data_test_config(
    data[nrow(data):1, ], settings
  ))
  testthat::expect_identical(reversed$data, prepared$data)
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
    data, c(series_variable = "city", series_order = "[Toronto]"))), "complete permutation")
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(data)),
    "unplotted estimation-group column 'city' varies")

  # A constant hidden estimation dimension is unambiguous and is retained.
  testthat::expect_identical(nrow(prepare_regression_plot_data(
    .render_data_test_config(left))$data), 24L)
})

testthat::test_that("plot keys are tuple-safe and independent of model identifiers", {
  data <- .render_data_test_fixture()
  copy <- data
  copy$model_id <- paste0(copy$model_id, "_copy")
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
    rbind(data, copy))), "duplicate plotting keys")
  testthat::expect_error(load_regression_results(.render_data_test_config(
    slices = list(data, data))), "duplicate saved coefficient/interval keys")

  tricky <- data[c(1:3, 19:21), ]
  tricky$model_config_id <- rep(c("A|B", "A"), each = 3)
  tricky$period <- rep(c("C", "B|C"), each = 3)
  testthat::expect_identical(nrow(prepare_regression_plot_data(
    .render_data_test_config(tricky))$data), 2L)
})

testthat::test_that("incompatible selected specifications fail with the differing field", {
  data <- .render_data_test_fixture()
  changes <- list(
    dataset_id = "other_dataset", term = "other_term", explanatory_variables = "black|high",
    control_variables = "other_control", fixed_effects = "other_fe",
    estimator = "other_estimator", estimator_version = "2.0",
    inference_contract_id = "other_contract", preparation_top_share = .2,
    preparation_probability_threshold = .9,
    preparation_ranking_group_variables = "city",
    preparation_scenario_covariates = "period",
    preparation_candidate_covariates = "black"
  )
  # term is selected before compatibility checks, so unused terms may coexist.
  for (field in setdiff(names(changes), "term")) {
    changed <- data
    changed[changed$model_config_id == "model_b", field] <- changes[[field]]
    testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(changed)),
      paste0("incompatible '", field, "'"))
  }
  unused <- data
  unused$term <- "other_term"
  unused$estimator_version <- "unrelated_version"
  actual <- prepare_regression_plot_data(.render_data_test_config(rbind(data, unused)))
  testthat::expect_identical(nrow(actual$data), 24L)

  grouped <- data
  grouped$city <- "Toronto"
  rows <- grouped$model_config_id == "model_b"
  grouped$estimation_group_variables[rows] <- "model_config_id|period|city"
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(grouped)),
    "incompatible 'estimation_group_variables'")
  clustered <- data
  clustered$vcov_type[rows] <- "cluster"
  clustered$cluster_variables[rows] <- "position_fe"
  clustered$cluster_counts[rows] <- "position_fe=20"
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(clustered)),
    "incompatible 'cluster_variables'")
})

testthat::test_that("saved interval rows cannot disagree on their shared statistics", {
  data <- .render_data_test_fixture()
  changed <- data
  changed$p_value[[1L]] <- .02
  testthat::expect_error(load_regression_results(.render_data_test_config(changed)),
    "statistics or metadata disagree across saved intervals")
  changed <- data
  changed$conf_low[[1L]] <- data$conf_low[[3L]] - .01
  testthat::expect_error(load_regression_results(.render_data_test_config(changed)),
    "not nested by level")
  changed <- data
  changed$confidence_level[[1L]] <- .95
  testthat::expect_error(load_regression_results(.render_data_test_config(changed)),
    "duplicate saved coefficient/interval keys")

  mixed <- data
  mixed$city <- "Toronto"
  other <- mixed[1:3, ]
  other$term <- "high"
  other$estimation_group_variables <- "model_config_id|period|city"
  mixed$p_value[[1L]] <- .02
  mixed$city[[1L]] <- "Montreal"
  testthat::expect_error(load_regression_results(.render_data_test_config(rbind(mixed, other))),
    "statistics or metadata disagree across saved intervals")
  # Different unselected group schemas are otherwise legitimate saved results.
  mixed$p_value[[1L]] <- data$p_value[[1L]]
  testthat::expect_identical(nrow(prepare_regression_plot_data(
    .render_data_test_config(rbind(mixed, other)))$data), 24L)
})

testthat::test_that("result schema and missing selections fail before plotting", {
  data <- .render_data_test_fixture()
  for (field in REGRESSION_RESULT_CORE_COLUMNS) {
    missing <- data[setdiff(names(data), field)]
    testthat::expect_error(load_regression_results(.render_data_test_config(missing)),
      paste0("missing required result column.*", field))
  }
  testthat::expect_error(load_regression_results(.render_data_test_config(
    data[setdiff(names(data), "period")])), "missing declared estimation-group.*period")
  extra <- data
  extra$unexpected <- 1
  testthat::expect_error(load_regression_results(.render_data_test_config(extra)),
    "undocumented result column.*unexpected")
  for (field in c("term", "period_variable", "panel_variable", "series_variable")) {
    testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(
      data, stats::setNames("missing", field))),
      if (field == "term") "no rows match term" else "missing configured column")
  }
  sliced <- data[data$confidence_level == .9, ]
  testthat::expect_error(prepare_regression_plot_data(.render_data_test_config(sliced)),
    "no rows match term.*confidence level")
  empty <- data
  empty$period[[1L]] <- ""
  testthat::expect_error(load_regression_results(.render_data_test_config(empty)),
    "estimation-group column 'period' has empty values")
  intercept <- data
  intercept$term <- "(Intercept)"
  testthat::expect_identical(nrow(prepare_regression_plot_data(.render_data_test_config(
    intercept, c(term = "'(Intercept)'")))$data), 24L)
})

testthat::test_that("CSV and numeric integrity are checked without fitting a model", {
  data <- .render_data_test_fixture()
  bad_values <- list(
    estimate = "NaN", std_error = "-1", statistic = "Inf", p_value = "1.1",
    confidence_level = ".8", conf_low = "1", conf_high = "-1",
    n_input = "3.5", n_used = "0", n_missing_dropped = "0",
    n_estimator_dropped = "0", n_dropped = "0",
    preparation_top_share = "0", preparation_probability_threshold = "1.1",
    estimator = "", dataset_id = " ", explanatory_variables = "black|",
    control_variables = "black|black", cluster_counts = "position_fe=20"
  )
  for (field in names(bad_values)) {
    changed <- data
    changed[[field]][[1L]] <- bad_values[[field]]
    testthat::expect_error(load_regression_results(.render_data_test_config(changed)),
      "Invalid regression results", info = field)
  }
  path <- .render_data_test_config()
  csv <- load_render_config(path)$resolved_results_paths[[1L]]
  writeLines(c("a,b", "1,2,3"), csv)
  testthat::expect_error(load_regression_results(path), "inconsistent field counts")
  writeLines(c("a,a", "1,2"), csv)
  testthat::expect_error(load_regression_results(path), "headers must be nonempty and distinct")
  writeLines("a,b", csv)
  testthat::expect_error(load_regression_results(path), "at least one data row")
})

testthat::test_that("cluster metadata is validated but not used to recalculate inference", {
  data <- .render_data_test_fixture()
  data$vcov_type <- "cluster"
  data$cluster_variables <- "position_fe|year"
  data$cluster_counts <- "position_fe=20|year=5"
  actual <- load_regression_results(.render_data_test_config(data))
  testthat::expect_equal(actual$p_value, data$p_value)
  testthat::expect_equal(actual$conf_low, data$conf_low)
  for (counts in c("year=5|position_fe=20", "position_fe=1|year=5",
    "position_fe=401|year=5", "position_fe=20", "position_fe=x|year=5",
    "position_fe=20|year=5|")) {
    changed <- data
    changed$cluster_counts <- counts
    testthat::expect_error(load_regression_results(.render_data_test_config(changed)),
      "cluster_counts")
  }
})

testthat::test_that("extreme finite periods cannot overflow series positions", {
  data <- .render_data_test_fixture()
  data <- data[data$period %in% c(1970, 1980), ]
  data$period <- ifelse(data$period == 1970, "-1e308", "1e308")
  data$city <- "Toronto"
  data$estimation_group_variables <- "model_config_id|period|city"
  other <- data
  other$city <- "Montreal"
  prepared <- prepare_regression_plot_data(.render_data_test_config(
    rbind(data, other), c(series_variable = "city")
  ))
  testthat::expect_identical(prepared$period_order, c("-1e308", "1e308"))
  testthat::expect_equal(prepared$period_positions, c(10, 20))
  testthat::expect_true(all(is.finite(prepared$data$.plot_x)))
  testthat::expect_true(is.finite(prepared$cap_width))

  # Finite endpoints and a finite raw span can still overflow after dodging.
  data$period <- ifelse(data$period == "-1e308", "-8e307", "8e307")
  other <- data
  other$city <- "Montreal"
  prepared <- prepare_regression_plot_data(.render_data_test_config(
    rbind(data, other), c(series_variable = "city")
  ))
  testthat::expect_equal(prepared$period_positions, c(10, 20))
  built <- ggplot2::ggplot_build(build_regression_plot(prepared)[[1L]])
  testthat::expect_true(all(is.finite(built$layout$panel_params[[1L]]$x.range)))
  testthat::expect_equal(.render_period_positions("1.79e308"), 10)
  testthat::expect_equal(.render_period_positions(c("01", "1")), c(10, 20))
})

testthat::test_that("significance threshold is strict and independent of interval choice", {
  data <- .render_data_test_fixture()
  data$p_value <- rep(c(.049, .05, .051, .099, .1, .101), each = 3, length.out = nrow(data))
  prepared <- prepare_regression_plot_data(.render_data_test_config(data))
  testthat::expect_equal(prepared$data$.plot_alpha, rep(c(1, .3, .3, .3, .3, .3), 4))
  changed <- prepare_regression_plot_data(.render_data_test_config(data, c(
    significance_level = ".1", confidence_level = ".99"
  )))
  testthat::expect_equal(changed$data$.plot_alpha, rep(c(1, 1, 1, 1, .3, .3), 4))
})

testthat::test_that("the estimator's saved CSV feeds rendering without schema adaptation", {
  directory <- tempfile("estimate-to-render-")
  dir.create(directory)
  regression_path <- file.path(directory, "regression.yaml")
  writeLines(c(
    paste0("data_path: ", yaml_quote(regression_fixture("regression_ready_known.csv"))),
    "dataset_id: known_fixture", "model_id: clustered_example",
    "outcome_variable: pick_top", "explanatory_variables: [black]",
    "control_variables: [high]", "fixed_effects: [position_fe]",
    "cluster_variables: [position_fe]", "estimation_group_variables: [period]",
    "output_directory: saved"
  ), regression_path)
  testthat::expect_message(results <- run_regressions(regression_path), "Estimated 2 fit")
  render_path <- file.path(directory, "render.yaml")
  writeLines(c(
    "results_paths: [saved/regression_results.csv]", "output_path: figure.png",
    "term: black", "confidence_level: .99", "period_variable: period",
    "panel_variable: outcome_variable"
  ), render_path)
  prepared <- prepare_regression_plot_data(render_path)
  expected <- results[results$term == "black" & results$confidence_level == .99, ]
  testthat::expect_identical(nrow(prepared$data), 2L)
  testthat::expect_identical(prepared$panel_order, "pick_top")
  testthat::expect_identical(prepared$data$estimator, rep("fixest::feols", 2))
  testthat::expect_identical(prepared$data$cluster_counts, rep("position_fe=4", 2))
  for (field in c("estimate", "std_error", "p_value", "conf_low", "conf_high")) {
    testthat::expect_equal(prepared$data[[field]], expected[[field]], tolerance = 1e-14)
  }
})
