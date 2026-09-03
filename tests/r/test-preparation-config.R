testthat::test_that("minimal preparation config applies exact defaults", {
  config <- load_preparation_config(
    regression_fixture("preparation_minimal.yaml")
  )

  testthat::expect_s3_class(config, "preparation_config")
  testthat::expect_equal(
    config$input_paths,
    c("raw_jobs_a.csv", "raw_jobs_b.csv")
  )
  testthat::expect_equal(config$output_path, "output/regression_ready.csv")
  testthat::expect_identical(config$audit_id, "fixture_audit")
  testthat::expect_equal(config$top_share, 0.08)
  testthat::expect_equal(config$probability_threshold, 0.99)
  testthat::expect_identical(
    config$ranking_group_variables,
    c("city", "year")
  )
  testthat::expect_identical(config$scenario_covariates, character())
  testthat::expect_identical(config$candidate_covariates, character())
  testthat::expect_true(all(file.exists(config$resolved_input_paths)))
})

testthat::test_that("fully specified preparation config preserves overrides", {
  config <- load_preparation_config(regression_fixture("preparation_full.yaml"))

  testthat::expect_identical(config$audit_id, "fixture_audit")
  testthat::expect_equal(config$top_share, 0.2)
  testthat::expect_equal(config$probability_threshold, 0.95)
  testthat::expect_identical(
    config$ranking_group_variables,
    c("city", "year", "model_config_id")
  )
  testthat::expect_identical(config$scenario_covariates, "job_category")
  testthat::expect_identical(config$candidate_covariates, "black")
})

testthat::test_that("relative paths resolve from the YAML directory", {
  config_path <- regression_fixture("preparation_minimal.yaml")
  previous <- setwd(tempdir())
  on.exit(setwd(previous), add = TRUE)

  config <- load_preparation_config(config_path)

  testthat::expect_equal(
    basename(config$resolved_input_paths),
    c("raw_jobs_a.csv", "raw_jobs_b.csv")
  )
  testthat::expect_equal(
    dirname(config$resolved_output_path),
    file.path(dirname(normalizePath(config_path)), "output")
  )
  testthat::expect_false(any(grepl("^/", config$input_paths)))
})

testthat::test_that("config rejects unknown, missing, and wrong-shape fields", {
  input <- regression_fixture("raw_jobs_a.csv")
  output <- tempfile(fileext = ".csv")

  unknown <- write_test_config(input, output, "mystery: true")
  testthat::expect_error(
    load_preparation_config(unknown),
    "unknown field.*mystery"
  )

  scalar_input <- write_test_config(
    input,
    output,
    input_as_sequence = FALSE
  )
  testthat::expect_error(
    load_preparation_config(scalar_input),
    "input_paths.*YAML list"
  )

  missing_output <- tempfile(fileext = ".yaml")
  writeLines(
    c(
      "input_paths:",
      sprintf("  - %s", yaml_quote(input)),
      "audit_id: test_audit"
    ),
    missing_output
  )
  testthat::expect_error(
    load_preparation_config(missing_output),
    "missing required field.*output_path"
  )

  missing_audit <- write_test_config(input, output)
  lines <- readLines(missing_audit, warn = FALSE)
  writeLines(lines[!startsWith(lines, "audit_id:")], missing_audit)
  testthat::expect_error(
    load_preparation_config(missing_audit),
    "missing required field.*audit_id"
  )

  for (replacement in c("audit_id: ''", "audit_id: []", "audit_id: null")) {
    invalid_audit <- write_test_config(input, output)
    lines <- readLines(invalid_audit, warn = FALSE)
    lines[startsWith(lines, "audit_id:")] <- replacement
    writeLines(lines, invalid_audit)
    testthat::expect_error(
      load_preparation_config(invalid_audit),
      "audit_id.*one nonempty string"
    )
  }

  top_level_sequence <- tempfile(fileext = ".yaml")
  writeLines(c("- one", "- two"), top_level_sequence)
  testthat::expect_error(
    load_preparation_config(top_level_sequence),
    "top level must be a YAML mapping"
  )

  malformed <- tempfile(fileext = ".yaml")
  writeLines(
    c("input_paths: [", "output_path: out.csv", "audit_id: test_audit"),
    malformed
  )
  testthat::expect_error(
    load_preparation_config(malformed),
    "YAML could not be parsed"
  )

  testthat::expect_error(
    load_preparation_config(tempfile("missing-config-", fileext = ".yaml")),
    "config file does not exist"
  )

  scalar_groups <- write_test_config(
    input,
    output,
    "ranking_group_variables: city"
  )
  testthat::expect_error(
    load_preparation_config(scalar_groups),
    "ranking_group_variables.*YAML list"
  )
})

testthat::test_that("config rejects invalid ranges and list values", {
  input <- regression_fixture("raw_jobs_a.csv")
  output <- tempfile(fileext = ".csv")

  for (line in c("top_share: 0", "top_share: 1.01", "top_share: '0.08'")) {
    path <- write_test_config(input, output, line)
    testthat::expect_error(load_preparation_config(path), "top_share.*\\(0, 1\\]")
  }
  for (line in c(
    "probability_threshold: -0.1",
    "probability_threshold: 2",
    "probability_threshold: null"
  )) {
    path <- write_test_config(input, output, line)
    testthat::expect_error(
      load_preparation_config(path),
      "probability_threshold.*\\(0, 1\\]"
    )
  }

  empty_groups <- write_test_config(
    input,
    output,
    "ranking_group_variables: []"
  )
  testthat::expect_error(
    load_preparation_config(empty_groups),
    "ranking_group_variables.*must not be empty"
  )

  duplicate_groups <- write_test_config(
    input,
    output,
    c("ranking_group_variables:", "  - city", "  - city")
  )
  testthat::expect_error(
    load_preparation_config(duplicate_groups),
    "duplicate value 'city'"
  )
})

testthat::test_that("config validates covariates and pre-ranking fields", {
  input <- regression_fixture("raw_jobs_a.csv")
  output <- tempfile(fileext = ".csv")

  reserved <- write_test_config(
    input,
    output,
    c("candidate_covariates:", "  - pick")
  )
  testthat::expect_error(load_preparation_config(reserved), "reserved column 'pick'")

  internal_scenario <- write_test_config(
    input,
    output,
    c("scenario_covariates:", "  - raw_pick")
  )
  testthat::expect_error(
    load_preparation_config(internal_scenario),
    "reserved column 'raw_pick'"
  )

  internal_candidate <- write_test_config(
    input,
    output,
    c("candidate_covariates:", "  - raw_log_probability")
  )
  testthat::expect_error(
    load_preparation_config(internal_candidate),
    "reserved column 'raw_log_probability'"
  )

  payload <- write_test_config(
    input,
    output,
    c("scenario_covariates:", "  - raw_response")
  )
  testthat::expect_error(load_preparation_config(payload), "payload-text field")

  overlap <- write_test_config(
    input,
    output,
    c(
      "scenario_covariates:",
      "  - treatment",
      "candidate_covariates:",
      "  - treatment"
    )
  )
  testthat::expect_error(load_preparation_config(overlap), "covariates overlap")

  post_ranking <- write_test_config(
    input,
    output,
    c("ranking_group_variables:", "  - pick_top")
  )
  testthat::expect_error(
    load_preparation_config(post_ranking),
    "not available before ranking"
  )

  generic_id <- write_test_config(
    input,
    output,
    c("scenario_covariates:", "  - id")
  )
  testthat::expect_identical(
    load_preparation_config(generic_id)$scenario_covariates,
    "id"
  )
})

testthat::test_that("config rejects duplicate, missing, and colliding paths", {
  input <- regression_fixture("raw_jobs_a.csv")
  output <- tempfile(fileext = ".csv")

  duplicate <- write_test_config(c(input, input), output)
  testthat::expect_error(load_preparation_config(duplicate), "duplicate")

  normalized_duplicate <- write_test_config(
    c(input, file.path(dirname(input), ".", basename(input))),
    output
  )
  testthat::expect_error(
    load_preparation_config(normalized_duplicate),
    "duplicate"
  )

  missing <- write_test_config(
    tempfile("missing-input-", fileext = ".csv"),
    output
  )
  testthat::expect_error(load_preparation_config(missing), "does not exist")

  collision <- write_test_config(input, input)
  testthat::expect_error(load_preparation_config(collision), "distinct")

  wrong_extension <- write_test_config(input, tempfile(fileext = ".txt"))
  testthat::expect_error(load_preparation_config(wrong_extension), "output_path.*csv")

  non_csv_input <- tempfile(fileext = ".txt")
  writeLines("not,csv", non_csv_input)
  non_csv_config <- write_test_config(non_csv_input, output)
  testthat::expect_error(
    load_preparation_config(non_csv_config),
    "every input path.*csv"
  )

  input_directory <- tempfile(fileext = ".csv")
  dir.create(input_directory)
  input_directory_config <- write_test_config(input_directory, output)
  testthat::expect_error(
    load_preparation_config(input_directory_config),
    "input path is a directory"
  )

  output_directory <- tempfile(fileext = ".csv")
  dir.create(output_directory)
  output_directory_config <- write_test_config(input, output_directory)
  testthat::expect_error(
    load_preparation_config(output_directory_config),
    "output_path.*directory"
  )

  unresolved_home <- paste0(
    "~llm-auditkit-user-",
    Sys.getpid(),
    "/input.csv"
  )
  testthat::skip_if_not(
    identical(path.expand(unresolved_home), unresolved_home),
    "generated home shorthand unexpectedly resolves"
  )
  unresolved_home_config <- write_test_config(unresolved_home, output)
  testthat::expect_error(
    load_preparation_config(unresolved_home_config),
    "home-directory shorthand cannot be expanded"
  )
})

testthat::test_that("absolute source provenance remains lexical", {
  directory <- tempfile("source-symlink-")
  dir.create(directory)
  target <- regression_fixture("raw_jobs_a.csv")
  alias <- file.path(directory, "alias.csv")
  testthat::skip_if_not(
    isTRUE(file.symlink(target, alias)),
    "filesystem does not permit symlinks"
  )
  config_path <- write_test_config(alias, tempfile(fileext = ".csv"))

  config <- load_preparation_config(config_path)

  testthat::expect_identical(config$input_paths, gsub("/+", "/", alias))
  testthat::expect_identical(
    config$resolved_input_paths,
    normalizePath(target, winslash = "/", mustWork = TRUE)
  )

  home_parent_path <- "~/../input.csv"
  testthat::expect_identical(
    .preparation_path_label(home_parent_path),
    .preparation_normalize_lexical_path(
      file.path(path.expand("~"), "..", "input.csv")
    )
  )
  testthat::expect_true(
    .preparation_is_absolute_path(.preparation_path_label(home_parent_path))
  )
})
