preparation_candidate_key <- function(data) {
  do.call(
    paste,
    c(data[PREPARATION_LONG_KEY_COLUMNS], list(sep = "/"))
  )
}

read_raw_fixture <- function(name) {
  utils::read.csv(
    regression_fixture(name),
    check.names = FALSE,
    colClasses = "character",
    na.strings = character(),
    stringsAsFactors = FALSE
  )
}

write_character_csv <- function(data, path) {
  utils::write.table(
    data,
    path,
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

write_multi_config <- function(
  directory,
  first,
  second,
  output = file.path(directory, "output", "ready.csv"),
  reverse_files = FALSE,
  override_lines = character()
) {
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  first_path <- write_character_csv(first, file.path(directory, "part-a.csv"))
  second_path <- write_character_csv(second, file.path(directory, "part-b.csv"))
  inputs <- c(basename(first_path), basename(second_path))
  if (reverse_files) {
    inputs <- rev(inputs)
  }
  config_path <- file.path(directory, "preparation.yaml")
  writeLines(
    c(
      "input_paths:",
      paste0("  - ", inputs),
      sprintf("output_path: %s", yaml_quote(output)),
      "audit_id: multi_fixture_audit",
      override_lines,
      "scenario_covariates:",
      "  - job_category",
      "candidate_covariates:",
      "  - black"
    ),
    config_path,
    useBytes = TRUE
  )
  config_path
}

mutated_multi_config <- function(
  mutate_first = identity,
  mutate_second = identity,
  output = tempfile(fileext = ".csv"),
  override_lines = character()
) {
  directory <- tempfile("mutated-preparation-")
  write_multi_config(
    directory,
    mutate_first(read_raw_fixture("raw_preparation_multi_a.csv")),
    mutate_second(read_raw_fixture("raw_preparation_multi_b.csv")),
    output = output,
    override_lines = override_lines
  )
}

testthat::test_that("preparation reshapes dynamic N and applies exact defaults", {
  data <- prepare_regression_data(
    regression_fixture("preparation_multi.yaml")
  )

  testthat::expect_equal(nrow(data), 22L)
  testthat::expect_identical(unique(data$audit_id), "multi_fixture_audit")
  testthat::expect_identical(
    names(data),
    c(
      PREPARATION_OUTPUT_CORE_COLUMNS,
      "job_category",
      "black"
    )
  )
  testthat::expect_equal(sum(data$pick), 10L)
  testthat::expect_equal(sum(data$pick_top), 3L)
  testthat::expect_equal(sum(data$pick_threshold), 6L)
  testthat::expect_true(any(data$candidate_index == 11L))
  testthat::expect_true(any(data$candidate_count == 11L))
  testthat::expect_true(any(data$candidate_count == 1L))
  testthat::expect_setequal(
    unique(data$city),
    c("Montreal", "Toronto", "Vancouver")
  )
  testthat::expect_setequal(unique(data$year), c(2010L, 2020L))
  testthat::expect_false(any(data$scenario_id == "job-005"))

  integer_fields <- c(
    "candidate_index",
    "candidate_count",
    "year",
    "pick",
    "pick_top",
    "pick_threshold"
  )
  testthat::expect_true(all(vapply(data[integer_fields], is.integer, logical(1))))
  testthat::expect_type(data$log_probability, "double")
  testthat::expect_type(data$preparation_top_share, "double")
  testthat::expect_type(data$preparation_probability_threshold, "double")

  keys <- preparation_candidate_key(data)
  testthat::expect_setequal(
    keys[data$pick_top == 1L],
    c(
      "job-001/persona-a/model-b/cand-001-a",
      "job-003/persona-a/model-a/cand-003-01",
      "job-004/persona-c/model-c/cand-004-a"
    )
  )
  testthat::expect_setequal(
    keys[data$pick_threshold == 1L],
    c(
      "job-001/persona-a/model-b/cand-001-a",
      "job-001/persona-b/model-a/cand-001-a",
      "job-002/persona-a/model-a/cand-002-a",
      "job-003/persona-a/model-a/cand-003-01",
      "job-003/persona-a/model-a/cand-003-02",
      "job-004/persona-c/model-c/cand-004-a"
    )
  )

  high_confidence_no <- keys ==
    "job-001/persona-b/model-a/cand-001-c"
  testthat::expect_identical(data$pick[high_confidence_no], 0L)
  testthat::expect_identical(data$pick_top[high_confidence_no], 0L)
  testthat::expect_identical(data$pick_threshold[high_confidence_no], 0L)

  report <- attr(data, "preparation_report", exact = TRUE)
  testthat::expect_identical(report$total_jobs, 7L)
  testthat::expect_identical(report$completed_jobs, 6L)
  testthat::expect_identical(report$excluded_jobs, 1L)
  testthat::expect_identical(report$excluded_by_status, c(failed = 1L))
})

testthat::test_that("preparation honors ranking and threshold overrides", {
  config <- mutated_multi_config(
    override_lines = c(
      "top_share: 0.25",
      "probability_threshold: 0.95",
      "ranking_group_variables:",
      "  - city"
    )
  )

  data <- prepare_regression_data(config)
  keys <- preparation_candidate_key(data)

  testthat::expect_equal(sum(data$pick_top), 6L)
  testthat::expect_equal(sum(data$pick_threshold), 10L)
  testthat::expect_setequal(
    keys[data$pick_top == 1L],
    c(
      "job-001/persona-a/model-b/cand-001-a",
      "job-001/persona-b/model-a/cand-001-a",
      "job-003/persona-a/model-a/cand-003-01",
      "job-003/persona-a/model-a/cand-003-02",
      "job-003/persona-a/model-a/cand-003-03",
      "job-004/persona-c/model-c/cand-004-a"
    )
  )
  testthat::expect_true(
    data$pick_threshold[
      keys == "job-004/persona-c/model-c/cand-004-b"
    ] == 1L
  )
  testthat::expect_true(all(data$preparation_top_share == 0.25))
  testthat::expect_true(
    all(data$preparation_probability_threshold == 0.95)
  )
  testthat::expect_true(
    all(data$preparation_ranking_group_variables == "city")
  )

  candidate_count_config <- mutated_multi_config(
    override_lines = c(
      "ranking_group_variables:",
      "  - city",
      "  - year",
      "  - candidate_count"
    )
  )
  candidate_count_data <- prepare_regression_data(candidate_count_config)
  testthat::expect_equal(sum(candidate_count_data$pick_top), 4L)
  testthat::expect_true(
    all(
      candidate_count_data$preparation_ranking_group_variables ==
        "city|year|candidate_count"
    )
  )
})

testthat::test_that("top-share cutoffs are stable at decimal boundaries", {
  candidates <- data.frame(
    scenario_id = sprintf("scenario-%03d", seq_len(100L)),
    persona_id = rep("persona", 100L),
    model_config_id = rep("model", 100L),
    candidate_id = sprintf("candidate-%03d", seq_len(100L)),
    city = rep("Toronto", 100L),
    pick = rep(1L, 100L),
    log_probability = -seq_len(100L) / 1000,
    stringsAsFactors = FALSE
  )
  config <- list(
    top_share = 0.07,
    probability_threshold = 0.99,
    ranking_group_variables = "city"
  )

  prepared <- .preparation_construct_outcomes(candidates, config)

  testthat::expect_gt(0.07 * 100, 7)
  testthat::expect_identical(sum(prepared$pick_top), 7L)
  testthat::expect_identical(
    which(prepared$pick_top == 1L),
    seq_len(7L)
  )
  testthat::expect_identical(
    .preparation_top_cutoff(1e-20, 1L),
    1L
  )
})

testthat::test_that("multi-field groups do not depend on joined labels", {
  values <- data.frame(
    first = c("a", "a|b", "a", "a|b"),
    second = c("b|c", "c", "b|c", "c"),
    stringsAsFactors = FALSE
  )

  groups <- .preparation_group_ids(values, c("first", "second"))

  testthat::expect_identical(groups[[1L]], groups[[3L]])
  testthat::expect_identical(groups[[2L]], groups[[4L]])
  testthat::expect_false(groups[[1L]] == groups[[2L]])
})

testthat::test_that("preparation is invariant to file and source-row order", {
  first <- read_raw_fixture("raw_preparation_multi_a.csv")
  second <- read_raw_fixture("raw_preparation_multi_b.csv")
  normal_config <- write_multi_config(
    tempfile("normal-order-"),
    first,
    second
  )
  shuffled_config <- write_multi_config(
    tempfile("shuffled-order-"),
    first[rev(seq_len(nrow(first))), , drop = FALSE],
    second[rev(seq_len(nrow(second))), , drop = FALSE],
    reverse_files = TRUE
  )

  normal <- prepare_regression_data(normal_config)
  shuffled <- prepare_regression_data(shuffled_config)

  testthat::expect_identical(shuffled, normal)
})

testthat::test_that("scenario consistency uses integer year semantics", {
  equivalent_years <- mutated_multi_config(
    mutate_first = function(data) {
      row <- data$scenario_id == "job-001" & data$persona_id == "persona-b"
      data$year[row] <- "+2010"
      data
    }
  )

  prepared <- prepare_regression_data(equivalent_years)

  testthat::expect_true(all(prepared$year == as.integer(prepared$year)))
  testthat::expect_true(all(
    prepared$year[prepared$scenario_id == "job-001"] == 2010L
  ))
})

testthat::test_that("preparation validates candidate families before combining", {
  missing_family <- mutated_multi_config(
    mutate_second = function(data) {
      data[c("candidate_10_pick")] <- NULL
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(missing_family),
    "candidate family 'pick'.*same indices"
  )

  above_count <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_3_id[data$scenario_id == "job-004"] <- "unexpected"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(above_count),
    "candidate_3_id.*populated above candidate_count"
  )

  blank_active_id <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_1_id[data$scenario_id == "job-004"] <- ""
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(blank_active_id),
    "candidate 1 has an empty stable ID"
  )

  implausibly_large_count <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_count[data$scenario_id == "job-003"] <- "2147483647"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(implausibly_large_count),
    "contiguous indices 1 through max\\(candidate_count\\)=2147483647"
  )
})

testthat::test_that("preparation validates stable candidate identity and covariates", {
  duplicate_candidate <- mutated_multi_config(
    mutate_second = function(data) {
      row <- data$scenario_id == "job-004"
      data$candidate_2_id[row] <- data$candidate_1_id[row]
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(duplicate_candidate),
    "Duplicate candidate identity"
  )

  changed_set <- mutated_multi_config(
    mutate_first = function(data) {
      row <- data$scenario_id == "job-001" & data$persona_id == "persona-b"
      data$candidate_3_id[row] <- "different-candidate"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(changed_set),
    "inconsistent candidate-ID sets"
  )

  conflicting_covariate <- mutated_multi_config(
    mutate_first = function(data) {
      row <- data$scenario_id == "job-001" & data$persona_id == "persona-b"
      data$candidate_1_black[row] <- "0"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(conflicting_covariate),
    "candidate 'cand-001-a'.*inconsistent 'black'"
  )
})

testthat::test_that("preparation validates completed picks and probabilities", {
  invalid_pick <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_3_pick[data$scenario_id == "job-003"] <- "1.0"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(invalid_pick),
    "invalid pick '1.0'"
  )

  missing_positive_probability <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_3_log_probability[data$scenario_id == "job-003"] <- ""
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(missing_positive_probability),
    "Raw-positive candidate 'cand-003-03' is missing"
  )

  invalid_probability <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_3_log_probability[data$scenario_id == "job-003"] <- "0.1"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(invalid_probability),
    "invalid log_probability '0.1'"
  )

  for (value in c("NaN", "Inf", "-Inf", "not-a-number")) {
    non_finite_probability <- mutated_multi_config(
      mutate_second = function(data) {
        data$candidate_3_log_probability[
          data$scenario_id == "job-003"
        ] <- value
        data
      }
    )
    testthat::expect_error(
      prepare_regression_data(non_finite_probability),
      "expected a finite number at most zero"
    )
  }

  ignored_failed_values <- mutated_multi_config(
    mutate_second = function(data) {
      row <- data$scenario_id == "job-005"
      data$candidate_1_pick[row] <- "not-binary"
      data$candidate_1_log_probability[row] <- "NaN"
      data
    }
  )
  testthat::expect_equal(
    nrow(prepare_regression_data(ignored_failed_values)),
    22L
  )
})

testthat::test_that("preparation rejects empty configured ranking values", {
  blank_group <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_3_black[data$scenario_id == "job-003"] <- ""
      data
    },
    override_lines = c(
      "ranking_group_variables:",
      "  - black"
    )
  )

  testthat::expect_error(
    prepare_regression_data(blank_group),
    "Ranking-group field 'black' is empty"
  )
})

testthat::test_that("preparation errors when no completed jobs remain", {
  no_completed <- mutated_multi_config(
    mutate_first = function(data) {
      data$result_status <- "failed"
      data
    },
    mutate_second = function(data) {
      data$result_status <- "cancelled"
      data
    }
  )
  testthat::expect_error(
    prepare_regression_data(no_completed),
    "No completed experiment jobs remain; excluded 7"
  )
})

testthat::test_that("runner writes repeatable CSV and preserves output on failure", {
  output <- file.path(tempfile("prepared-output-"), "nested", "ready.csv")
  config <- mutated_multi_config(output = output)

  testthat::expect_message(
    run_regression_preparation(config),
    paste0(
      "Prepared 22 candidate row.*6 completed job.*",
      "excluded 1 non-completed job.*failed=1"
    )
  )
  testthat::expect_true(file.exists(output))
  first_bytes <- readBin(output, "raw", n = file.info(output)$size)

  testthat::expect_message(
    run_regression_preparation(config),
    "Prepared 22 candidate row"
  )
  second_bytes <- readBin(output, "raw", n = file.info(output)$size)
  testthat::expect_identical(second_bytes, first_bytes)

  invalid_config <- mutated_multi_config(
    mutate_second = function(data) {
      data$candidate_1_log_probability[data$scenario_id == "job-003"] <- ""
      data
    },
    output = output
  )
  testthat::expect_error(
    run_regression_preparation(invalid_config),
    "Raw-positive candidate 'cand-003-01' is missing"
  )
  testthat::expect_identical(
    readBin(output, "raw", n = file.info(output)$size),
    first_bytes
  )
  testthat::expect_length(
    list.files(
      dirname(output),
      pattern = paste0("^\\.", basename(output), "-.*\\.tmp$")
    ),
    0L
  )
})

testthat::test_that("preparation CLI accepts exactly --config path", {
  output <- file.path(tempfile("cli-output-"), "ready.csv")
  config <- mutated_multi_config(output = output)
  script <- file.path(
    REGRESSION_PROJECT_ROOT,
    "scripts",
    "prepare_regression_data.R"
  )
  previous <- setwd(tempdir())
  on.exit(setwd(previous), add = TRUE)

  testthat::expect_error(
    .preparation_parse_cli_args(c("--config", config, "extra")),
    "Usage:"
  )
  testthat::expect_error(
    .preparation_parse_cli_args(c("--unknown", config)),
    "Usage:"
  )

  success <- system2(
    "Rscript",
    c(shQuote(script), "--config", shQuote(config)),
    stdout = TRUE,
    stderr = TRUE
  )
  success_status <- attr(success, "status", exact = TRUE)
  if (is.null(success_status)) {
    success_status <- 0L
  }
  testthat::expect_identical(success_status, 0L)
  testthat::expect_true(file.exists(output))
  testthat::expect_match(paste(success, collapse = "\n"), "Prepared 22")

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
    "Usage: Rscript scripts/prepare_regression_data.R --config <path>",
    fixed = TRUE
  )
})
