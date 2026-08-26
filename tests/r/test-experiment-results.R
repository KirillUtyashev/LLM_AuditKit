testthat::test_that("loader combines explicit inputs with lexical provenance", {
  config <- load_preparation_config(
    regression_fixture("preparation_minimal.yaml")
  )

  data <- load_experiment_results(config)

  testthat::expect_equal(nrow(data), 3L)
  testthat::expect_identical(names(data)[1L], "source_file")
  testthat::expect_identical(data$scenario_id, c("001", "002", "003"))
  testthat::expect_identical(
    data$source_file,
    c("raw_jobs_a.csv", "raw_jobs_a.csv", "raw_jobs_b.csv")
  )
  testthat::expect_true(all(vapply(data, is.character, logical(1))))
  testthat::expect_identical(data$result_status, c("completed", "failed", "completed"))
  testthat::expect_true(is.na(data$candidate_3_id[1L]))
  testthat::expect_identical(data$candidate_3_id[3L], "C-3")
  testthat::expect_false(any(c("row_id", "row_index") %in% names(data)))
})

testthat::test_that("loader follows configured file order", {
  config_path <- write_test_config(
    c(
      regression_fixture("raw_jobs_b.csv"),
      regression_fixture("raw_jobs_a.csv")
    ),
    tempfile(fileext = ".csv")
  )

  data <- load_experiment_results(config_path)

  testthat::expect_identical(data$scenario_id, c("003", "001", "002"))
  testthat::expect_identical(
    data$source_file,
    c(
      regression_fixture("raw_jobs_b.csv"),
      regression_fixture("raw_jobs_a.csv"),
      regression_fixture("raw_jobs_a.csv")
    )
  )
})

testthat::test_that("loader rejects missing envelope fields and blank IDs", {
  directory <- tempfile("raw-errors-")
  missing_id <- write_raw_csv(
    directory,
    "missing-id.csv",
    sub("scenario_id,", "", minimal_raw_header, fixed = TRUE),
    "persona,model,completed,1,Toronto,2010"
  )
  missing_config <- write_test_config(missing_id, tempfile(fileext = ".csv"))
  testthat::expect_error(
    load_experiment_results(missing_config),
    "missing required column.*scenario_id"
  )

  blank_id <- write_raw_csv(
    directory,
    "blank-id.csv",
    minimal_raw_header,
    ",persona,model,completed,1,Toronto,2010"
  )
  blank_config <- write_test_config(blank_id, tempfile(fileext = ".csv"))
  testthat::expect_error(
    load_experiment_results(blank_config),
    "column 'scenario_id' is empty at source row 1"
  )
})

testthat::test_that("loader validates integer envelope fields", {
  directory <- tempfile("integer-errors-")

  for (candidate_count in c("0", "1.5", "2147483648")) {
    path <- write_raw_csv(
      directory,
      paste0("candidate-count-", gsub("\\.", "-", candidate_count), ".csv"),
      minimal_raw_header,
      paste(
        "010",
        "persona",
        "model",
        "completed",
        candidate_count,
        "Toronto",
        "2010",
        sep = ","
      )
    )
    config <- write_test_config(path, tempfile(fileext = ".csv"))
    testthat::expect_error(
      load_experiment_results(config),
      "candidate_count.*positive integers"
    )
  }

  for (year in c("20x0", "2147483648")) {
    path <- write_raw_csv(
      directory,
      paste0("year-", year, ".csv"),
      minimal_raw_header,
      paste(
        "010",
        "persona",
        "model",
        "completed",
        "1",
        "Toronto",
        year,
        sep = ","
      )
    )
    config <- write_test_config(path, tempfile(fileext = ".csv"))
    testthat::expect_error(
      load_experiment_results(config),
      "year.*must contain integers"
    )
  }
})

testthat::test_that("loader rejects duplicate job keys within and across files", {
  directory <- tempfile("duplicate-jobs-")
  row <- "010,persona,model,completed,1,Toronto,2010"
  duplicate_within <- write_raw_csv(
    directory,
    "within.csv",
    minimal_raw_header,
    c(row, row)
  )
  within_config <- write_test_config(
    duplicate_within,
    tempfile(fileext = ".csv")
  )
  testthat::expect_error(
    load_experiment_results(within_config),
    "Duplicate ExperimentJobKey.*scenario_id=010"
  )

  first <- write_raw_csv(directory, "first.csv", minimal_raw_header, row)
  second <- write_raw_csv(directory, "second.csv", minimal_raw_header, row)
  across_config <- write_test_config(
    c(first, second),
    tempfile(fileext = ".csv")
  )
  testthat::expect_error(
    load_experiment_results(across_config),
    "Duplicate ExperimentJobKey.*first.csv.*second.csv"
  )
})

testthat::test_that("loader rejects malformed, duplicate, and empty CSV structures", {
  directory <- tempfile("csv-errors-")
  malformed <- write_raw_csv(
    directory,
    "malformed.csv",
    minimal_raw_header,
    "010,persona,model,completed,1,Toronto"
  )
  malformed_config <- write_test_config(malformed, tempfile(fileext = ".csv"))
  testthat::expect_error(
    load_experiment_results(malformed_config),
    "inconsistent field counts"
  )

  duplicate_header <- write_raw_csv(
    directory,
    "duplicate-header.csv",
    paste0(minimal_raw_header, ",scenario_id"),
    "010,persona,model,completed,1,Toronto,2010,again"
  )
  duplicate_header_config <- write_test_config(
    duplicate_header,
    tempfile(fileext = ".csv")
  )
  testthat::expect_error(
    load_experiment_results(duplicate_header_config),
    "duplicate header 'scenario_id'"
  )

  empty <- write_raw_csv(directory, "empty.csv", minimal_raw_header)
  empty_config <- write_test_config(empty, tempfile(fileext = ".csv"))
  testthat::expect_error(
    load_experiment_results(empty_config),
    "header and at least one data row"
  )

  reserved_source <- write_raw_csv(
    directory,
    "reserved-source.csv",
    paste0(minimal_raw_header, ",source_file"),
    "010,persona,model,completed,1,Toronto,2010,user-value"
  )
  reserved_source_config <- write_test_config(
    reserved_source,
    tempfile(fileext = ".csv")
  )
  testthat::expect_error(
    load_experiment_results(reserved_source_config),
    "reserved column 'source_file'"
  )
})

testthat::test_that("loader handles quoted multiline fields", {
  directory <- tempfile("multiline-csv-")
  multiline <- write_raw_csv(
    directory,
    "multiline.csv",
    paste0(minimal_raw_header, ",notes"),
    c(
      "011,persona,model,completed,1,Toronto,2010,\"first line",
      "second line\""
    )
  )
  config <- write_test_config(multiline, tempfile(fileext = ".csv"))

  data <- load_experiment_results(config)

  testthat::expect_equal(nrow(data), 1L)
  testthat::expect_identical(data$notes, "first line\nsecond line")
})

testthat::test_that("loader validates configured covariates and scenario consistency", {
  directory <- tempfile("covariate-errors-")
  missing_candidate <- write_raw_csv(
    directory,
    "missing-candidate.csv",
    paste0(minimal_raw_header, ",job_category"),
    "020,persona,model,completed,1,Toronto,2010,administrative"
  )
  missing_candidate_config <- write_test_config(
    missing_candidate,
    tempfile(fileext = ".csv"),
    c(
      "scenario_covariates:",
      "  - job_category",
      "candidate_covariates:",
      "  - black"
    )
  )
  testthat::expect_error(
    load_experiment_results(missing_candidate_config),
    "missing configured candidate family.*black"
  )

  conflicting <- write_raw_csv(
    directory,
    "conflicting.csv",
    minimal_raw_header,
    c(
      "021,persona-a,model,completed,1,Toronto,2010",
      "021,persona-b,model,completed,1,Montreal,2010"
    )
  )
  conflicting_config <- write_test_config(
    conflicting,
    tempfile(fileext = ".csv")
  )
  testthat::expect_error(
    load_experiment_results(conflicting_config),
    "Scenario '021' has inconsistent 'city'"
  )
})
