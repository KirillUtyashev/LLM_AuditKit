.regression_execution_read_fixture <- function() {
  utils::read.csv(
    regression_fixture("regression_ready_known.csv"),
    check.names = FALSE,
    na.strings = "",
    stringsAsFactors = FALSE
  )
}

.regression_execution_write_csv <- function(data, path) {
  utils::write.table(
    data,
    file = path,
    sep = ",",
    row.names = FALSE,
    col.names = TRUE,
    quote = TRUE,
    qmethod = "double",
    na = "",
    eol = "\n",
    fileEncoding = "UTF-8"
  )
  path
}

.regression_execution_yaml_list <- function(field, values) {
  if (length(values) == 0L) {
    return(sprintf("%s: []", field))
  }
  c(
    sprintf("%s:", field),
    paste0("  - ", vapply(values, yaml_quote, character(1)))
  )
}

.regression_execution_config <- function(
  data = .regression_execution_read_fixture(),
  directory = tempfile("regression-execution-"),
  data_name = "ready.csv",
  config_name = "regression.yaml",
  dataset_id = "known_fixture",
  model_id = "known_model",
  outcome = "pick_top",
  explanatory = "black",
  controls = "high",
  fixed_effects = "position_fe",
  clusters = character(),
  groups = "period",
  output_directory = "results"
) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  .regression_execution_write_csv(data, file.path(directory, data_name))
  config_path <- file.path(directory, config_name)
  writeLines(
    c(
      sprintf("data_path: %s", yaml_quote(data_name)),
      sprintf("dataset_id: %s", yaml_quote(dataset_id)),
      sprintf("model_id: %s", yaml_quote(model_id)),
      sprintf("outcome_variable: %s", yaml_quote(outcome)),
      .regression_execution_yaml_list(
        "explanatory_variables",
        explanatory
      ),
      .regression_execution_yaml_list("control_variables", controls),
      .regression_execution_yaml_list("fixed_effects", fixed_effects),
      .regression_execution_yaml_list("cluster_variables", clusters),
      .regression_execution_yaml_list(
        "estimation_group_variables",
        groups
      ),
      sprintf("output_directory: %s", yaml_quote(output_directory))
    ),
    config_path,
    useBytes = TRUE
  )
  config_path
}

.regression_execution_bytes <- function(path) {
  readBin(path, what = "raw", n = as.integer(file.info(path)$size))
}

.regression_execution_group_counts <- function(results, period) {
  rows <- results$period == period
  counts <- unique(results[
    rows,
    c(
      "n_input",
      "n_complete",
      "n_used",
      "n_missing_dropped",
      "n_estimator_dropped",
      "n_dropped"
    ),
    drop = FALSE
  ])
  class(counts) <- "data.frame"
  attr(counts, "regression_fit_count") <- NULL
  attr(counts, "regression_results_contract_id") <- NULL
  row.names(counts) <- NULL
  counts
}

testthat::test_that("grouped IID fixed-effects results satisfy the tidy contract", {
  config_path <- .regression_execution_config(
    model_id = "fe_iid",
    clusters = character(),
    groups = "period"
  )

  results <- estimate_regressions(config_path)

  testthat::expect_identical(
    class(results),
    c("regression_results", "data.frame")
  )
  testthat::expect_true(is.data.frame(results))
  testthat::expect_identical(
    attr(results, "regression_results_contract_id", exact = TRUE),
    REGRESSION_RESULTS_OBJECT_CONTRACT_ID
  )
  testthat::expect_identical(
    names(results),
    c(REGRESSION_RESULT_CORE_COLUMNS, "period")
  )
  testthat::expect_identical(nrow(results), 12L)
  testthat::expect_identical(
    attr(results, "regression_fit_count", exact = TRUE),
    2L
  )
  testthat::expect_identical(
    results$period,
    rep(c(2010L, 2020L), each = 6L)
  )
  testthat::expect_identical(
    results$term,
    rep(rep(c("black", "high"), each = 3L), 2L)
  )
  testthat::expect_equal(
    results$confidence_level,
    rep(REGRESSION_CONFIDENCE_LEVELS, 4L)
  )

  testthat::expect_true(all(results$dataset_id == "known_fixture"))
  testthat::expect_true(all(results$model_id == "fe_iid"))
  testthat::expect_true(all(results$estimator == "fixest::feols"))
  testthat::expect_true(
    all(results$estimator_version == as.character(packageVersion("fixest")))
  )
  testthat::expect_true(
    all(results$inference_contract_id == "fixest_feols_ssc_v1")
  )
  testthat::expect_true(all(results$outcome_variable == "pick_top"))
  testthat::expect_true(all(results$vcov_type == "iid"))
  testthat::expect_true(all(results$explanatory_variables == "black"))
  testthat::expect_true(all(results$control_variables == "high"))
  testthat::expect_true(all(results$fixed_effects == "position_fe"))
  testthat::expect_true(all(results$cluster_variables == ""))
  testthat::expect_true(all(results$estimation_group_variables == "period"))
  testthat::expect_true(all(results$cluster_counts == ""))
  testthat::expect_true(all(results$preparation_top_share == 0.5))
  testthat::expect_true(
    all(results$preparation_probability_threshold == 0.99)
  )
  testthat::expect_true(
    all(results$preparation_ranking_group_variables == "city|year")
  )
  testthat::expect_true(
    all(results$preparation_scenario_covariates == "position_fe|period")
  )
  testthat::expect_true(
    all(results$preparation_candidate_covariates == "black|high")
  )
  testthat::expect_true(all(results$n_input == 32L))
  testthat::expect_true(all(results$n_complete == 32L))
  testthat::expect_true(all(results$n_used == 32L))
  testthat::expect_true(all(results$n_missing_dropped == 0L))
  testthat::expect_true(all(results$n_estimator_dropped == 0L))
  testthat::expect_true(all(results$n_dropped == 0L))

  coefficient_rows <- results$confidence_level == 0.95
  coefficient_results <- results[coefficient_rows, , drop = FALSE]
  testthat::expect_equal(
    coefficient_results$estimate,
    c(-0.25, 0.25, 0.25, -0.25),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    coefficient_results$std_error,
    rep(0.16984155512168936, 4L),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    coefficient_results$statistic,
    c(-1, 1, 1, -1) * 1.4719601443879742,
    tolerance = 1e-12
  )
  testthat::expect_equal(
    coefficient_results$p_value,
    rep(0.15303372450418032, 4L),
    tolerance = 1e-12
  )

  black_2010 <- results$period == 2010L & results$term == "black"
  testthat::expect_equal(
    results$conf_low[black_2010],
    c(
      -0.5396847999353357,
      -0.5991143164575186,
      -0.7219411975799526
    ),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    results$conf_high[black_2010],
    c(
      0.03968479993533575,
      0.09911431645751867,
      0.22194119757995273
    ),
    tolerance = 1e-12
  )

  statistic_columns <- c("estimate", "std_error", "statistic", "p_value")
  coefficient_keys <- interaction(results$period, results$term, drop = TRUE)
  for (rows in split(seq_len(nrow(results)), coefficient_keys)) {
    testthat::expect_identical(
      nrow(unique(results[rows, statistic_columns, drop = FALSE])),
      1L
    )
  }
})

testthat::test_that("clustered inference uses locked finite-sample intervals", {
  results <- estimate_regressions(
    .regression_execution_config(
      model_id = "fe_clustered",
      clusters = "position_fe",
      groups = "period"
    )
  )

  testthat::expect_identical(nrow(results), 12L)
  testthat::expect_true(all(results$vcov_type == "cluster"))
  testthat::expect_true(all(results$cluster_variables == "position_fe"))
  testthat::expect_true(all(results$cluster_counts == "position_fe=4"))

  black_2010 <- results$period == 2010L & results$term == "black"
  black_rows <- results[black_2010, , drop = FALSE]
  testthat::expect_equal(
    black_rows$estimate,
    rep(-0.25, 3L),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    black_rows$std_error,
    rep(0.14923174911033082, 3L),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    black_rows$statistic,
    rep(-1.6752467319482303, 3L),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    black_rows$p_value,
    rep(0.19247929718946027, 3L),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    black_rows$conf_low,
    c(
      -0.6011965416677724,
      -0.7249220285871976,
      -1.1216491126863235
    ),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    black_rows$conf_high,
    c(
      0.10119654166777237,
      0.22492202858719762,
      0.6216491126863235
    ),
    tolerance = 1e-12
  )

  clustered_95 <- black_rows$confidence_level == 0.95
  clustered_width <-
    black_rows$conf_high[clustered_95] - black_rows$conf_low[clustered_95]
  normal_width <-
    2 * stats::qnorm(0.975) * black_rows$std_error[clustered_95]
  testthat::expect_gt(clustered_width, normal_width)

  multiway <- estimate_regressions(
    .regression_execution_config(
      model_id = "fe_multiway_clustered",
      clusters = c("position_fe", "model_config_id"),
      groups = "period"
    )
  )
  testthat::expect_true(all(multiway$vcov_type == "cluster"))
  testthat::expect_true(
    all(multiway$cluster_variables == "position_fe|model_config_id")
  )
  testthat::expect_true(
    all(multiway$cluster_counts == "position_fe=4|model_config_id=2")
  )
})

testthat::test_that("two-field grouped fits are ordered by group, term, and level", {
  results <- estimate_regressions(
    .regression_execution_config(
      model_id = "two_field_groups",
      clusters = "position_fe",
      groups = c("period", "model_config_id")
    )
  )

  testthat::expect_identical(
    names(results),
    c(REGRESSION_RESULT_CORE_COLUMNS, "period", "model_config_id")
  )
  testthat::expect_identical(nrow(results), 24L)
  testthat::expect_identical(
    attr(results, "regression_fit_count", exact = TRUE),
    4L
  )
  expected_group <- rep(
    c("2010/model-a", "2010/model-b", "2020/model-a", "2020/model-b"),
    each = 6L
  )
  testthat::expect_identical(
    paste(results$period, results$model_config_id, sep = "/"),
    expected_group
  )
  testthat::expect_identical(
    results$term,
    rep(rep(c("black", "high"), each = 3L), 4L)
  )
  testthat::expect_equal(
    results$confidence_level,
    rep(REGRESSION_CONFIDENCE_LEVELS, 8L)
  )
  testthat::expect_true(all(results$n_input == 16L))
  testthat::expect_true(all(results$n_used == 16L))
  testthat::expect_true(all(results$cluster_counts == "position_fe=2"))
  testthat::expect_true(
    all(
      results$estimation_group_variables == "period|model_config_id"
    )
  )

  coefficient_results <- results[
    results$confidence_level == 0.95,
    ,
    drop = FALSE
  ]
  testthat::expect_equal(
    coefficient_results$estimate,
    c(-0.25, 0.25, -0.25, 0.25, 0.25, -0.25, 0.25, -0.25),
    tolerance = 1e-12
  )
  testthat::expect_equal(
    coefficient_results$std_error,
    rep(0.26854307776478742, 8L),
    tolerance = 1e-12
  )
})

testthat::test_that("multiple requested explanatory variables are estimated in every group", {
  results <- estimate_regressions(
    .regression_execution_config(
      model_id = "multiple_explanatory_variables",
      explanatory = c("black", "high"),
      controls = character(),
      clusters = character(),
      groups = c("period", "model_config_id")
    )
  )

  testthat::expect_s3_class(results, "regression_results")
  testthat::expect_identical(
    names(results),
    c(REGRESSION_RESULT_CORE_COLUMNS, "period", "model_config_id")
  )
  testthat::expect_identical(
    attr(results, "regression_fit_count", exact = TRUE),
    4L
  )
  testthat::expect_identical(nrow(results), 24L)
  testthat::expect_true(all(results$explanatory_variables == "black|high"))
  testthat::expect_true(all(results$control_variables == ""))

  group_labels <- paste(results$period, results$model_config_id, sep = "/")
  for (group_label in unique(group_labels)) {
    group_rows <- which(group_labels == group_label)
    testthat::expect_setequal(
      unique(results$term[group_rows]),
      c("black", "high")
    )
    for (term in c("black", "high")) {
      term_rows <- group_rows[results$term[group_rows] == term]
      testthat::expect_identical(length(term_rows), 3L)
      testthat::expect_equal(
        results$confidence_level[term_rows],
        REGRESSION_CONFIDENCE_LEVELS
      )
      testthat::expect_identical(
        length(unique(results$estimate[term_rows])),
        1L
      )
      testthat::expect_identical(
        length(unique(results$std_error[term_rows])),
        1L
      )
      testthat::expect_identical(
        length(unique(results$p_value[term_rows])),
        1L
      )
      testthat::expect_true(
        all(results$conf_low[term_rows] <= results$estimate[term_rows])
      )
      testthat::expect_true(
        all(results$conf_high[term_rows] >= results$estimate[term_rows])
      )
    }
  }
})

testthat::test_that("an ungrouped model without fixed effects retains its intercept", {
  results <- estimate_regressions(
    .regression_execution_config(
      model_id = "iid_intercept",
      fixed_effects = character(),
      clusters = character(),
      groups = character()
    )
  )

  testthat::expect_identical(names(results), REGRESSION_RESULT_CORE_COLUMNS)
  testthat::expect_identical(nrow(results), 9L)
  testthat::expect_identical(
    attr(results, "regression_fit_count", exact = TRUE),
    1L
  )
  testthat::expect_identical(
    results$term,
    rep(c("(Intercept)", "black", "high"), each = 3L)
  )
  testthat::expect_true(all(results$n_input == 64L))
  testthat::expect_true(all(results$n_used == 64L))
  testthat::expect_true(all(results$fixed_effects == ""))
  testthat::expect_true(all(results$estimation_group_variables == ""))

  coefficient_results <- results[
    results$confidence_level == 0.95,
    ,
    drop = FALSE
  ]
  testthat::expect_equal(
    coefficient_results$estimate,
    c(0.5, 0, 0),
    tolerance = 1e-12
  )

  logical_data <- .regression_execution_read_fixture()
  logical_data$black <- as.logical(logical_data$black)
  logical_results <- estimate_regressions(
    .regression_execution_config(
      data = logical_data,
      model_id = "logical_regressor",
      groups = "period"
    )
  )
  testthat::expect_true("black" %in% logical_results$term)
  testthat::expect_false("blackTRUE" %in% logical_results$term)

  multiple_fe <- estimate_regressions(
    .regression_execution_config(
      model_id = "multiple_fixed_effects",
      fixed_effects = c("position_fe", "model_config_id"),
      groups = "period"
    )
  )
  testthat::expect_identical(nrow(multiple_fe), 12L)
  testthat::expect_true(
    all(multiple_fe$fixed_effects == "position_fe|model_config_id")
  )
})

testthat::test_that("regression-ready input semantics are validated", {
  missing_column <- .regression_execution_read_fixture()
  missing_column$candidate_count <- NULL
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = missing_column,
        model_id = "missing_core"
      )
    ),
    "missing required regression-ready column.*candidate_count"
  )

  duplicate_identity <- .regression_execution_read_fixture()
  identity <- c(
    "scenario_id",
    "persona_id",
    "model_config_id",
    "candidate_id"
  )
  duplicate_identity[2L, identity] <- duplicate_identity[1L, identity]
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = duplicate_identity,
        model_id = "duplicate_identity"
      )
    ),
    "duplicate stable candidate identity"
  )

  mixed_provenance <- .regression_execution_read_fixture()
  mixed_provenance$preparation_top_share[[1L]] <- 0.25
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = mixed_provenance,
        model_id = "mixed_provenance"
      )
    ),
    "preparation_top_share.*mixes multiple preparation settings"
  )

  invalid_subset <- .regression_execution_read_fixture()
  negative_row <- which(invalid_subset$pick == 0L)[[1L]]
  invalid_subset$pick_top[[negative_row]] <- 1L
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = invalid_subset,
        model_id = "invalid_subset"
      )
    ),
    "pick_top must be a subset of pick"
  )

  invalid_threshold <- .regression_execution_read_fixture()
  invalid_threshold$pick_threshold[[1L]] <-
    1L - invalid_threshold$pick_threshold[[1L]]
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = invalid_threshold,
        model_id = "invalid_threshold"
      )
    ),
    "pick_threshold is inconsistent"
  )

  invalid_index <- .regression_execution_read_fixture()
  invalid_index$candidate_index[[1L]] <-
    invalid_index$candidate_count[[1L]] + 1L
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = invalid_index,
        model_id = "invalid_index"
      )
    ),
    "candidate_index exceeds candidate_count"
  )

  missing_positive_probability <- .regression_execution_read_fixture()
  positive_row <- which(missing_positive_probability$pick == 1L)[[1L]]
  missing_positive_probability$log_probability[[positive_row]] <- NA_real_
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = missing_positive_probability,
        model_id = "missing_positive_probability"
      )
    ),
    "raw-positive row is missing log_probability"
  )

  nonnumeric_model <- .regression_execution_read_fixture()
  nonnumeric_model$black <- as.character(nonnumeric_model$black)
  nonnumeric_model$black[[1L]] <- "unknown"
  testthat::expect_error(
    estimate_regressions(
      .regression_execution_config(
        data = nonnumeric_model,
        model_id = "nonnumeric_model"
      )
    ),
    "model column 'black' must be numeric or logical"
  )
})

testthat::test_that("complete-case and estimator removals are accounted separately", {
  missing_data <- .regression_execution_read_fixture()
  missing_data$analysis_outcome <- missing_data$pick_top
  missing_data$analysis_black <- missing_data$black
  missing_data$analysis_fe <- missing_data$position_fe
  missing_data$analysis_cluster <- missing_data$position_fe
  rows_2010 <- which(missing_data$period == 2010L)
  missing_data$analysis_outcome[rows_2010[[1L]]] <- NA
  missing_data$analysis_black[rows_2010[[10L]]] <- NA
  missing_data$analysis_fe[rows_2010[[19L]]] <- NA
  missing_data$analysis_cluster[rows_2010[[28L]]] <- NA

  missing_results <- estimate_regressions(
    .regression_execution_config(
      data = missing_data,
      model_id = "missingness",
      outcome = "analysis_outcome",
      explanatory = "analysis_black",
      controls = "high",
      fixed_effects = "analysis_fe",
      clusters = "analysis_cluster",
      groups = "period"
    )
  )
  testthat::expect_identical(
    .regression_execution_group_counts(missing_results, 2010L),
    data.frame(
      n_input = 32L,
      n_complete = 28L,
      n_used = 28L,
      n_missing_dropped = 4L,
      n_estimator_dropped = 0L,
      n_dropped = 4L
    )
  )
  testthat::expect_identical(
    .regression_execution_group_counts(missing_results, 2020L),
    data.frame(
      n_input = 32L,
      n_complete = 32L,
      n_used = 32L,
      n_missing_dropped = 0L,
      n_estimator_dropped = 0L,
      n_dropped = 0L
    )
  )

  singleton_data <- .regression_execution_read_fixture()
  singleton_data$analysis_fe <- singleton_data$position_fe
  singleton_rows_2010 <- which(singleton_data$period == 2010L)
  singleton_data$analysis_fe[singleton_rows_2010[[1L]]] <- "singleton"
  singleton_results <- estimate_regressions(
    .regression_execution_config(
      data = singleton_data,
      model_id = "singleton_drop",
      fixed_effects = "analysis_fe",
      clusters = character(),
      groups = "period"
    )
  )
  testthat::expect_identical(
    .regression_execution_group_counts(singleton_results, 2010L),
    data.frame(
      n_input = 32L,
      n_complete = 32L,
      n_used = 31L,
      n_missing_dropped = 0L,
      n_estimator_dropped = 1L,
      n_dropped = 1L
    )
  )
})

testthat::test_that("invalid or unidentified specifications fail explicitly", {
  collinear_data <- .regression_execution_read_fixture()
  collinear_data$black_copy <- collinear_data$black
  collinear_config <- .regression_execution_config(
    data = collinear_data,
    model_id = "collinear",
    explanatory = c("black", "black_copy"),
    groups = "period"
  )
  testthat::expect_error(
    estimate_regressions(collinear_config),
    "removed through collinearity: black_copy"
  )

  no_complete_data <- .regression_execution_read_fixture()
  no_complete_data$analysis_outcome <- NA_real_
  no_complete_config <- .regression_execution_config(
    data = no_complete_data,
    model_id = "no_complete_cases",
    outcome = "analysis_outcome",
    groups = "period"
  )
  testthat::expect_error(
    estimate_regressions(no_complete_config),
    "no complete cases remain"
  )

  one_cluster_data <- .regression_execution_read_fixture()
  one_cluster_data$one_cluster <- "only"
  one_cluster_config <- .regression_execution_config(
    data = one_cluster_data,
    model_id = "one_cluster",
    clusters = "one_cluster",
    groups = "period"
  )
  testthat::expect_error(
    estimate_regressions(one_cluster_config),
    "fewer than two used-sample clusters"
  )

  post_removal_cluster_data <- .regression_execution_read_fixture()
  post_removal_cluster_data$analysis_fe <- "main"
  post_removal_cluster_data$analysis_fe[[1L]] <- "singleton"
  post_removal_cluster_data$analysis_cluster <- "remaining"
  post_removal_cluster_data$analysis_cluster[[1L]] <- "removed"
  post_removal_cluster_config <- .regression_execution_config(
    data = post_removal_cluster_data,
    model_id = "post_removal_one_cluster",
    fixed_effects = "analysis_fe",
    clusters = "analysis_cluster",
    groups = "period"
  )
  testthat::expect_error(
    estimate_regressions(post_removal_cluster_config),
    "cluster variable 'analysis_cluster' has fewer than two used-sample clusters"
  )

  singleton_data <- .regression_execution_read_fixture()
  singleton_data$unique_fe <- paste(
    singleton_data$scenario_id,
    singleton_data$candidate_id,
    sep = "/"
  )
  singleton_config <- .regression_execution_config(
    data = singleton_data,
    model_id = "unidentified_singletons",
    fixed_effects = "unique_fe",
    groups = "period"
  )
  testthat::expect_error(
    estimate_regressions(singleton_config),
    "All observations are fixed-effects singletons"
  )

  missing_group_data <- .regression_execution_read_fixture()
  missing_group_data$analysis_group <- missing_group_data$period
  missing_group_data$analysis_group[[1L]] <- NA
  missing_group_config <- .regression_execution_config(
    data = missing_group_data,
    model_id = "missing_group",
    groups = "analysis_group"
  )
  testthat::expect_error(
    estimate_regressions(missing_group_config),
    "estimation-group column 'analysis_group' is empty"
  )

  infinite_fe_data <- .regression_execution_read_fixture()
  infinite_fe_data$numeric_fe <- match(
    infinite_fe_data$position_fe,
    unique(infinite_fe_data$position_fe)
  )
  infinite_fe_data$numeric_fe[[1L]] <- Inf
  infinite_fe_config <- .regression_execution_config(
    data = infinite_fe_data,
    model_id = "infinite_fixed_effect",
    fixed_effects = "numeric_fe",
    groups = "period"
  )
  testthat::expect_error(
    estimate_regressions(infinite_fe_config),
    "fixed-effect or cluster column 'numeric_fe' contains a non-finite value"
  )
})

testthat::test_that("stable input ordering produces identical tidy results", {
  data <- .regression_execution_read_fixture()
  original <- estimate_regressions(
    .regression_execution_config(
      data = data,
      model_id = "order_invariant",
      clusters = "position_fe",
      groups = c("period", "model_config_id")
    )
  )
  reversed <- estimate_regressions(
    .regression_execution_config(
      data = data[rev(seq_len(nrow(data))), , drop = FALSE],
      model_id = "order_invariant",
      clusters = "position_fe",
      groups = c("period", "model_config_id")
    )
  )

  testthat::expect_identical(reversed, original)
})

testthat::test_that("in-memory regression results can be written safely", {
  results <- estimate_regressions(
    .regression_execution_config(
      model_id = "public_writer",
      clusters = character(),
      groups = "period"
    )
  )
  directory <- tempfile("regression-results-writer-")
  output_path <- file.path(directory, "nested", "results.csv")

  returned_path <- testthat::expect_invisible(
    write_regression_results(results, output_path)
  )
  testthat::expect_identical(returned_path, output_path)
  testthat::expect_true(file.exists(output_path))
  column_classes <- vapply(
    results,
    function(values) {
      switch(
        typeof(values),
        integer = "integer",
        double = "numeric",
        logical = "logical",
        character = "character"
      )
    },
    character(1)
  )
  written <- utils::read.csv(
    output_path,
    check.names = FALSE,
    na.strings = character(),
    stringsAsFactors = FALSE,
    colClasses = column_classes
  )
  expected <- results
  class(expected) <- "data.frame"
  attr(expected, "regression_fit_count") <- NULL
  attr(expected, "regression_results_contract_id") <- NULL
  testthat::expect_equal(written, expected, tolerance = 1e-14)

  original_bytes <- .regression_execution_bytes(output_path)
  invalid_results <- results
  invalid_results$confidence_level[[1L]] <- 0.80
  testthat::expect_error(
    write_regression_results(invalid_results, output_path),
    "each term and estimation group must contain one internally consistent"
  )
  testthat::expect_identical(
    .regression_execution_bytes(output_path),
    original_bytes
  )

  invalid_version <- results
  invalid_version$estimator_version[[1L]] <- "different"
  testthat::expect_error(
    write_regression_results(invalid_version, output_path),
    "estimator_version.*constant"
  )
  invalid_counts <- results
  tampered_term_rows <- seq_len(3L)
  invalid_counts$n_used[tampered_term_rows] <-
    invalid_counts$n_used[tampered_term_rows] - 1L
  invalid_counts$n_estimator_dropped[tampered_term_rows] <-
    invalid_counts$n_estimator_dropped[tampered_term_rows] + 1L
  invalid_counts$n_dropped[tampered_term_rows] <-
    invalid_counts$n_dropped[tampered_term_rows] + 1L
  testthat::expect_error(
    write_regression_results(invalid_counts, output_path),
    "n_used.*constant within each estimation group"
  )

  clustered <- estimate_regressions(
    .regression_execution_config(
      model_id = "public_writer_clustered",
      clusters = "position_fe",
      groups = "period"
    )
  )
  invalid_cluster_counts <- clustered
  invalid_cluster_counts$cluster_counts[clustered$period == 2010L] <-
    "position_fe=999"
  testthat::expect_error(
    write_regression_results(invalid_cluster_counts, output_path),
    "cluster_counts is inconsistent"
  )

  plain_results <- results
  class(plain_results) <- "data.frame"
  attr(plain_results, "regression_fit_count") <- NULL
  attr(plain_results, "regression_results_contract_id") <- NULL
  testthat::expect_error(
    write_regression_results(plain_results, output_path),
    "must be returned by estimate_regressions"
  )
  testthat::expect_error(
    write_regression_results(results, c("one.csv", "two.csv")),
    "must be one nonempty string"
  )
  testthat::expect_error(
    write_regression_results(results, file.path(directory, "results.txt")),
    "must end in '.csv'",
    fixed = TRUE
  )
  directory_path <- file.path(directory, "directory.csv")
  dir.create(directory_path)
  testthat::expect_error(
    write_regression_results(results, directory_path),
    "output path is a directory"
  )
  testthat::expect_length(
    list.files(
      dirname(output_path),
      pattern = "^\\.results\\.csv-.*\\.tmp$",
      all.files = TRUE
    ),
    0L
  )
})

testthat::test_that("runner replacement is deterministic and preserves old output on failure", {
  directory <- tempfile("regression-runner-")
  config_path <- .regression_execution_config(
    directory = directory,
    config_name = "valid.yaml",
    data_name = "valid.csv",
    model_id = "atomic_runner",
    clusters = character(),
    groups = "period"
  )
  config <- load_regression_config(config_path)

  testthat::expect_message(
    first <- run_regressions(config),
    "Estimated 2 fit\\(s\\) and 4 coefficient\\(s\\); wrote 12 result row"
  )
  testthat::expect_true(file.exists(config$resolved_output_path))
  first_bytes <- .regression_execution_bytes(config$resolved_output_path)
  written <- utils::read.csv(
    config$resolved_output_path,
    check.names = FALSE,
    na.strings = character(),
    stringsAsFactors = FALSE
  )
  testthat::expect_identical(names(written), names(first))
  testthat::expect_identical(nrow(written), 12L)

  testthat::expect_message(
    run_regressions(config),
    "Estimated 2 fit\\(s\\) and 4 coefficient\\(s\\); wrote 12 result row"
  )
  second_bytes <- .regression_execution_bytes(config$resolved_output_path)
  testthat::expect_identical(second_bytes, first_bytes)

  serialization_path <- file.path(
    config$resolved_output_directory,
    "numeric_serialization.csv"
  )
  previous_options <- options(scipen = 999)
  on.exit(options(previous_options), add = TRUE)
  .regression_write_csv_atomic(
    data.frame(value = c(1e20, 1e-12)),
    serialization_path
  )
  expanded_bytes <- .regression_execution_bytes(serialization_path)
  options(scipen = 0)
  .regression_write_csv_atomic(
    data.frame(value = c(1e20, 1e-12)),
    serialization_path
  )
  scientific_bytes <- .regression_execution_bytes(serialization_path)
  testthat::expect_identical(scientific_bytes, expanded_bytes)

  invalid_data <- .regression_execution_read_fixture()
  invalid_data$black_copy <- invalid_data$black
  invalid_path <- .regression_execution_config(
    data = invalid_data,
    directory = directory,
    config_name = "invalid.yaml",
    data_name = "invalid.csv",
    model_id = "atomic_runner_invalid",
    explanatory = c("black", "black_copy"),
    clusters = character(),
    groups = "period"
  )
  testthat::expect_error(
    run_regressions(invalid_path),
    "removed through collinearity"
  )
  testthat::expect_identical(
    .regression_execution_bytes(config$resolved_output_path),
    first_bytes
  )
  testthat::expect_length(
    list.files(
      config$resolved_output_directory,
      pattern = "^\\.regression_results\\.csv-.*\\.tmp$",
      all.files = TRUE
    ),
    0L
  )

  testthat::expect_identical(
    .regression_parse_cli_args(c("--config", "regression.yaml")),
    "regression.yaml"
  )
  testthat::expect_error(
    .regression_parse_cli_args(c("regression.yaml")),
    "Usage: Rscript scripts/run_regression.R"
  )
})

testthat::test_that("regression CLI runs from outside the repository", {
  directory <- tempfile("regression-cli-")
  config_path <- .regression_execution_config(
    directory = directory,
    model_id = "cli_runner",
    clusters = character(),
    groups = "period"
  )
  config <- load_regression_config(config_path)
  script <- file.path(
    REGRESSION_PROJECT_ROOT,
    "scripts",
    "run_regression.R"
  )
  previous <- setwd(tempdir())
  on.exit(setwd(previous), add = TRUE)

  success <- system2(
    "Rscript",
    c(shQuote(script), "--config", shQuote(config_path)),
    stdout = TRUE,
    stderr = TRUE
  )
  success_status <- attr(success, "status", exact = TRUE)
  if (is.null(success_status)) {
    success_status <- 0L
  }
  testthat::expect_identical(success_status, 0L)
  testthat::expect_true(file.exists(config$resolved_output_path))
  testthat::expect_match(
    paste(success, collapse = "\n"),
    "Estimated 2 fit\\(s\\) and 4 coefficient\\(s\\); wrote 12 result row"
  )

  failure <- suppressWarnings(
    system2(
      "Rscript",
      shQuote(script),
      stdout = TRUE,
      stderr = TRUE
    )
  )
  testthat::expect_identical(attr(failure, "status", exact = TRUE), 1L)
  testthat::expect_match(
    paste(failure, collapse = "\n"),
    "Usage: Rscript scripts/run_regression.R --config <path>",
    fixed = TRUE
  )
})
