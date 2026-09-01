source(
  file.path(
    REGRESSION_PROJECT_ROOT,
    "R",
    "regression",
    "regression_config.R"
  ),
  local = TRUE
)

.write_regression_config_test_data <- function(directory) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  path <- file.path(directory, "ready.csv")
  writeLines("pick_top,black,scenario_id,city,period\n1,1,s1,Toronto,2020", path)
  path
}

.regression_config_test_lines <- function(
  data_path = "ready.csv",
  include_groups = FALSE,
  output_directory = "results"
) {
  lines <- c(
    sprintf("data_path: %s", yaml_quote(data_path)),
    "dataset_id: sample_slice",
    "model_id: black_callback",
    "outcome_variable: pick_top",
    "explanatory_variables:",
    "  - black",
    "control_variables: []",
    "fixed_effects:",
    "  - scenario_id",
    "cluster_variables:",
    "  - scenario_id"
  )
  if (include_groups) {
    lines <- c(lines, "estimation_group_variables:", "  - period", "  - city")
  }
  c(lines, sprintf("output_directory: %s", yaml_quote(output_directory)))
}

.write_regression_config_test <- function(
  lines = NULL,
  include_groups = FALSE,
  data_path = "ready.csv",
  output_directory = "results"
) {
  directory <- tempfile("regression-estimation-config-")
  dir.create(directory, recursive = TRUE)
  .write_regression_config_test_data(directory)
  config_path <- file.path(directory, "regression.yaml")
  if (is.null(lines)) {
    lines <- .regression_config_test_lines(
      data_path,
      include_groups,
      output_directory
    )
  }
  writeLines(lines, config_path, useBytes = TRUE)
  config_path
}

testthat::test_that("regression config exposes the exact public contracts", {
  testthat::expect_identical(
    REGRESSION_CONFIG_KEYS,
    c(
      "data_path", "dataset_id", "model_id", "outcome_variable",
      "explanatory_variables", "control_variables", "fixed_effects",
      "cluster_variables", "estimation_group_variables", "output_directory"
    )
  )
  testthat::expect_length(REGRESSION_RESULT_CORE_COLUMNS, 33L)
  testthat::expect_identical(
    REGRESSION_RESULT_CORE_COLUMNS,
    c(
      "dataset_id", "audit_id", "model_id", "estimator", "estimator_version",
      "inference_contract_id", "outcome_variable", "term", "estimate",
      "std_error", "statistic", "p_value", "n_input", "n_complete",
      "n_used", "n_missing_dropped", "n_estimator_dropped", "n_dropped",
      "confidence_level", "conf_low", "conf_high", "vcov_type",
      "explanatory_variables", "control_variables", "fixed_effects",
      "cluster_variables", "estimation_group_variables", "cluster_counts",
      "preparation_top_share", "preparation_probability_threshold",
      "preparation_ranking_group_variables", "preparation_scenario_covariates",
      "preparation_candidate_covariates"
    )
  )
})

testthat::test_that("minimal config resolves paths relative to its YAML", {
  config_path <- .write_regression_config_test()
  previous <- setwd(tempdir())
  on.exit(setwd(previous), add = TRUE)

  config <- load_regression_config(config_path)

  testthat::expect_s3_class(config, "regression_config")
  testthat::expect_identical(config$data_path, "ready.csv")
  testthat::expect_true(file.exists(config$resolved_data_path))
  testthat::expect_identical(config$dataset_id, "sample_slice")
  testthat::expect_identical(config$model_id, "black_callback")
  testthat::expect_identical(config$outcome_variable, "pick_top")
  testthat::expect_identical(config$explanatory_variables, "black")
  testthat::expect_identical(config$control_variables, character())
  testthat::expect_identical(config$fixed_effects, "scenario_id")
  testthat::expect_identical(config$cluster_variables, "scenario_id")
  testthat::expect_identical(config$estimation_group_variables, character())
  testthat::expect_identical(config$output_directory, "results")
  testthat::expect_identical(
    config$resolved_output_directory,
    file.path(dirname(normalizePath(config_path)), "results")
  )
  testthat::expect_identical(
    config$resolved_output_path,
    file.path(dirname(normalizePath(config_path)), "results", "regression_results.csv")
  )
})

testthat::test_that("explicit estimation groups preserve order", {
  config <- load_regression_config(
    .write_regression_config_test(include_groups = TRUE)
  )
  testthat::expect_identical(
    config$estimation_group_variables,
    c("period", "city")
  )
})

testthat::test_that("config rejects unknown, missing, and malformed fields", {
  valid <- .regression_config_test_lines()

  unknown <- .write_regression_config_test(c(valid, "mystery: true"))
  testthat::expect_error(load_regression_config(unknown), "unknown field.*mystery")

  missing_controls <- .write_regression_config_test(
    valid[!startsWith(valid, "control_variables:")]
  )
  testthat::expect_error(
    load_regression_config(missing_controls),
    "missing required field.*control_variables"
  )

  scalar_explanatory <- .write_regression_config_test(
    c(
      valid[seq_len(match("explanatory_variables:", valid) - 1L)],
      "explanatory_variables: black",
      valid[(match("  - black", valid) + 1L):length(valid)]
    )
  )
  testthat::expect_error(
    load_regression_config(scalar_explanatory),
    "explanatory_variables.*YAML list"
  )

  empty_explanatory <- .write_regression_config_test(
    sub("explanatory_variables:", "explanatory_variables: []", valid)[-6L]
  )
  testthat::expect_error(
    load_regression_config(empty_explanatory),
    "explanatory_variables.*must not be empty"
  )

  top_sequence <- .write_regression_config_test(c("- one", "- two"))
  testthat::expect_error(
    load_regression_config(top_sequence),
    "top level must be a YAML mapping"
  )

  malformed <- .write_regression_config_test(c("data_path: [", "dataset_id: x"))
  testthat::expect_error(load_regression_config(malformed), "YAML could not be parsed")

  testthat::expect_error(
    load_regression_config(tempfile("missing-regression-config-", fileext = ".yaml")),
    "config file does not exist"
  )
})

testthat::test_that("variable names, duplicates, and overlaps are rejected", {
  valid <- .regression_config_test_lines(include_groups = TRUE)

  for (field in c(
    "outcome_variable", "explanatory_variables", "control_variables",
    "fixed_effects", "cluster_variables", "estimation_group_variables"
  )) {
    audit_role <- valid
    if (field == "outcome_variable") {
      audit_role <- sub(
        "outcome_variable: pick_top",
        "outcome_variable: audit_id",
        audit_role
      )
    } else if (field == "control_variables") {
      audit_role <- sub(
        "control_variables: \\[\\]",
        "control_variables:\n  - audit_id",
        audit_role
      )
    } else {
      header <- match(paste0(field, ":"), audit_role)
      audit_role[[header + 1L]] <- "  - audit_id"
    }
    testthat::expect_error(
      load_regression_config(.write_regression_config_test(audit_role)),
      paste0("audit_id.*provenance.*", field),
      info = field
    )
  }

  invalid_name <- .write_regression_config_test(
    sub("outcome_variable: pick_top", "outcome_variable: 'pick + top'", valid)
  )
  testthat::expect_error(load_regression_config(invalid_name), "invalid column name")

  reserved_name <- .write_regression_config_test(
    sub("  - black", "  - if", valid)
  )
  testthat::expect_error(
    load_regression_config(reserved_name),
    "invalid column name"
  )

  duplicate_explanatory <- .write_regression_config_test(
    append(valid, "  - black", after = match("  - black", valid))
  )
  testthat::expect_error(
    load_regression_config(duplicate_explanatory),
    "duplicate value 'black'"
  )

  outcome_on_rhs <- .write_regression_config_test(
    sub("  - black", "  - pick_top", valid)
  )
  testthat::expect_error(load_regression_config(outcome_on_rhs), "right-hand side")

  overlapping_rhs <- .write_regression_config_test(
    sub("control_variables: \\[\\]", "control_variables:\n  - black", valid)
  )
  testthat::expect_error(load_regression_config(overlapping_rhs), "overlap at 'black'")

  reserved_group <- .write_regression_config_test(
    sub("  - period", "  - estimate", valid)
  )
  testthat::expect_error(
    load_regression_config(reserved_group),
    "estimate.*reserved result column"
  )

  testthat::expect_no_error(
    load_regression_config(.write_regression_config_test())
  )
})

testthat::test_that("data and output paths enforce their contracts", {
  missing <- .write_regression_config_test(data_path = "missing.csv")
  testthat::expect_error(load_regression_config(missing), "data CSV does not exist")

  wrong_extension <- .write_regression_config_test(data_path = "ready.txt")
  testthat::expect_error(load_regression_config(wrong_extension), "data_path.*csv")

  data_directory_config <- .write_regression_config_test(data_path = "input.csv")
  dir.create(file.path(dirname(data_directory_config), "input.csv"))
  testthat::expect_error(load_regression_config(data_directory_config), "data path is a directory")

  output_file_config <- .write_regression_config_test(output_directory = "output")
  writeLines("file", file.path(dirname(output_file_config), "output"))
  testthat::expect_error(load_regression_config(output_file_config), "existing file")

  collision_config <- .write_regression_config_test(
    data_path = "results/regression_results.csv",
    output_directory = "results"
  )
  collision_directory <- file.path(dirname(collision_config), "results")
  dir.create(collision_directory)
  file.copy(
    file.path(dirname(collision_config), "ready.csv"),
    file.path(collision_directory, "regression_results.csv")
  )
  testthat::expect_error(load_regression_config(collision_config), "distinct from 'data_path'")

  result_directory_config <- .write_regression_config_test(output_directory = "results")
  dir.create(
    file.path(dirname(result_directory_config), "results", "regression_results.csv"),
    recursive = TRUE
  )
  testthat::expect_error(
    load_regression_config(result_directory_config),
    "result path is a directory"
  )
})
