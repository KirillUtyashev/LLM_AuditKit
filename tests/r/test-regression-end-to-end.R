.regression_e2e_copy_files <- function(source, destination) {
  dir.create(destination, recursive = TRUE, showWarnings = FALSE)
  paths <- list.files(source, full.names = TRUE, all.files = FALSE)
  copied <- file.copy(paths, destination, overwrite = TRUE)
  if (length(copied) != length(paths) || !all(copied)) {
    stop("Could not copy the public regression end-to-end example.")
  }
  invisible(destination)
}

.regression_e2e_process_status <- function(output) {
  status <- attr(output, "status", exact = TRUE)
  if (is.null(status)) 0L else status
}

.regression_e2e_run_cli <- function(script_name, config_path) {
  script <- file.path(
    REGRESSION_PROJECT_ROOT,
    "scripts",
    script_name
  )
  output <- system2(
    file.path(R.home("bin"), "Rscript"),
    c(shQuote(script), "--config", shQuote(config_path)),
    stdout = TRUE,
    stderr = TRUE
  )
  list(
    status = .regression_e2e_process_status(output),
    output = output
  )
}

.regression_e2e_bytes <- function(path) {
  readBin(path, what = "raw", n = as.integer(file.info(path)$size))
}

.regression_e2e_png_dimensions <- function(path) {
  header <- readBin(path, what = "raw", n = 24L)
  signature <- as.raw(c(
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a
  ))
  stopifnot(
    length(header) == 24L,
    identical(header[seq_len(8L)], signature),
    identical(rawToChar(header[13:16]), "IHDR")
  )
  c(
    width = sum(as.integer(header[17:20]) * 256^(3:0)),
    height = sum(as.integer(header[21:24]) * 256^(3:0))
  )
}

.regression_e2e_aligned_candidates <- function(data) {
  fields <- c(
    "scenario_id",
    "candidate_id",
    "candidate_index",
    "candidate_count",
    "city",
    "year",
    "black",
    "high"
  )
  ordered <- order(
    data$scenario_id,
    data$candidate_id,
    method = "radix"
  )
  aligned <- data[ordered, fields, drop = FALSE]
  row.names(aligned) <- NULL
  aligned
}

testthat::test_that(
  "public raw shards run through preparation, grouped estimation, and rendering",
  {
    sandbox <- tempfile("regression-public-e2e-")
    dir.create(sandbox)
    on.exit(unlink(sandbox, recursive = TRUE, force = TRUE), add = TRUE)

    example_source <- file.path(
      REGRESSION_PROJECT_ROOT,
      "examples",
      "regression",
      "end_to_end"
    )
    fixture_source <- regression_fixture("end_to_end")
    example_directory <- file.path(
      sandbox,
      "examples",
      "regression",
      "end_to_end"
    )
    fixture_directory <- file.path(
      sandbox,
      "tests",
      "r",
      "fixtures",
      "regression",
      "end_to_end"
    )
    .regression_e2e_copy_files(example_source, example_directory)
    .regression_e2e_copy_files(fixture_source, fixture_directory)

    caller_directory <- file.path(sandbox, "unrelated-caller")
    dir.create(caller_directory)
    previous_directory <- setwd(caller_directory)
    on.exit(setwd(previous_directory), add = TRUE)

    preparation_configs <- c(
      a = file.path(example_directory, "prepare_audit_a.yaml"),
      b = file.path(example_directory, "prepare_audit_b.yaml")
    )
    regression_configs <- c(
      a = file.path(example_directory, "regress_audit_a.yaml"),
      b = file.path(example_directory, "regress_audit_b.yaml")
    )
    output_root <- file.path(
      sandbox,
      "outputs",
      "regression",
      "end_to_end"
    )
    prepared_paths <- c(
      a = file.path(output_root, "audit_a", "regression_ready.csv"),
      b = file.path(output_root, "audit_b", "regression_ready.csv")
    )
    result_paths <- c(
      a = file.path(output_root, "audit_a", "regression_results.csv"),
      b = file.path(output_root, "audit_b", "regression_results.csv")
    )
    audit_ids <- c(
      a = "synthetic_historian_model_a_run_001",
      b = "synthetic_historian_model_b_run_001"
    )
    model_config_ids <- c(
      a = "synthetic-model-a-v1",
      b = "synthetic-model-b-v1"
    )

    for (audit in names(preparation_configs)) {
      process <- .regression_e2e_run_cli(
        "prepare_regression_data.R",
        preparation_configs[[audit]]
      )
      diagnostic <- paste(process$output, collapse = "\n")
      testthat::expect_identical(process$status, 0L, info = diagnostic)
      testthat::expect_match(
        diagnostic,
        "Prepared 64 candidate row(s)",
        fixed = TRUE
      )
      testthat::expect_match(
        diagnostic,
        sprintf(
          "researcher-assigned audit_id '%s'",
          audit_ids[[audit]]
        ),
        fixed = TRUE
      )
      testthat::expect_match(
        diagnostic,
        "from 16 completed job(s); excluded 0 non-completed job(s)",
        fixed = TRUE
      )
    }

    prepared <- lapply(
      prepared_paths,
      utils::read.csv,
      check.names = FALSE,
      na.strings = "",
      stringsAsFactors = FALSE
    )
    expected_pick_counts <- c(a = 39L, b = 53L)
    expected_threshold_counts <- c(a = 23L, b = 38L)

    # This block is the explicit inspection boundary. Estimation starts only
    # after the two prepared audit artifacts pass these substantive checks.
    for (audit in names(prepared)) {
      data <- prepared[[audit]]
      testthat::expect_identical(nrow(data), 64L)
      testthat::expect_identical(
        names(data),
        c(PREPARATION_OUTPUT_CORE_COLUMNS, "black", "high")
      )
      testthat::expect_identical(unique(data$audit_id), audit_ids[[audit]])
      testthat::expect_identical(
        unique(data$persona_id),
        "synthetic-historian"
      )
      testthat::expect_identical(
        unique(data$model_config_id),
        model_config_ids[[audit]]
      )
      testthat::expect_length(unique(data$source_file), 2L)
      testthat::expect_setequal(
        unique(data$city),
        c("Montreal", "Toronto")
      )
      testthat::expect_setequal(unique(data$year), c(2010L, 2020L))
      testthat::expect_true(
        all(as.integer(table(data$city, data$year)) == 16L)
      )
      top_counts <- stats::aggregate(
        data$pick_top,
        data[c("city", "year")],
        sum
      )
      testthat::expect_true(all(top_counts$x == 2L))
      testthat::expect_identical(
        sum(data$pick),
        expected_pick_counts[[audit]]
      )
      testthat::expect_identical(sum(data$pick_top), 8L)
      testthat::expect_identical(
        sum(data$pick_threshold),
        expected_threshold_counts[[audit]]
      )
      threshold_recomputed <- as.integer(
        data$pick == 1L &
          data$log_probability >= log(0.99)
      )
      testthat::expect_identical(
        data$pick_threshold,
        threshold_recomputed
      )
      testthat::expect_true(all(data$preparation_top_share == 0.08))
      testthat::expect_true(
        all(data$preparation_probability_threshold == 0.99)
      )
      testthat::expect_true(
        all(data$preparation_ranking_group_variables == "city|year")
      )
      testthat::expect_true(
        all(data$preparation_candidate_covariates == "black|high")
      )
    }
    testthat::expect_identical(
      .regression_e2e_aligned_candidates(prepared$a),
      .regression_e2e_aligned_candidates(prepared$b)
    )
    testthat::expect_false(identical(
      unique(prepared$a$audit_id),
      unique(prepared$b$audit_id)
    ))

    prepared_bytes <- lapply(prepared_paths, .regression_e2e_bytes)
    for (audit in names(preparation_configs)) {
      process <- .regression_e2e_run_cli(
        "prepare_regression_data.R",
        preparation_configs[[audit]]
      )
      testthat::expect_identical(
        process$status,
        0L,
        info = paste(process$output, collapse = "\n")
      )
      testthat::expect_identical(
        .regression_e2e_bytes(prepared_paths[[audit]]),
        prepared_bytes[[audit]]
      )
    }

    for (audit in names(regression_configs)) {
      process <- .regression_e2e_run_cli(
        "run_regression.R",
        regression_configs[[audit]]
      )
      diagnostic <- paste(process$output, collapse = "\n")
      testthat::expect_identical(process$status, 0L, info = diagnostic)
      testthat::expect_match(
        diagnostic,
        "Estimated 4 fit(s) and 8 coefficient(s); wrote 24 result row(s)",
        fixed = TRUE
      )
    }

    results <- lapply(result_paths, read_regression_results)
    expected_black_estimates <- list(
      a = c(-0.25, -0.5, -0.5, -0.375),
      b = c(0.125, 0.25, 0.5, 0.125)
    )
    dataset_ids <- c(
      a = "synthetic_historian_model_a_full",
      b = "synthetic_historian_model_b_full"
    )

    for (audit in names(results)) {
      data <- results[[audit]]
      testthat::expect_identical(nrow(data), 24L)
      testthat::expect_identical(
        names(data),
        c(REGRESSION_RESULT_CORE_COLUMNS, "city", "year")
      )
      testthat::expect_identical(unique(data$audit_id), audit_ids[[audit]])
      testthat::expect_identical(
        unique(data$dataset_id),
        dataset_ids[[audit]]
      )
      testthat::expect_identical(
        unique(data$model_id),
        "black_high_by_city_year_fe"
      )
      testthat::expect_setequal(unique(data$term), c("black", "high"))
      testthat::expect_setequal(
        unique(data$confidence_level),
        c(0.90, 0.95, 0.99)
      )
      testthat::expect_true(all(data$outcome_variable == "pick_threshold"))
      testthat::expect_true(
        all(data$explanatory_variables == "black|high")
      )
      testthat::expect_true(all(data$control_variables == ""))
      testthat::expect_true(all(data$fixed_effects == "scenario_id"))
      testthat::expect_true(all(data$cluster_variables == "scenario_id"))
      testthat::expect_true(
        all(data$estimation_group_variables == "city|year")
      )
      testthat::expect_true(all(data$cluster_counts == "scenario_id=4"))
      for (field in c("n_input", "n_complete", "n_used")) {
        testthat::expect_true(all(data[[field]] == 16L), info = field)
      }
      for (field in c(
        "n_missing_dropped",
        "n_estimator_dropped",
        "n_dropped"
      )) {
        testthat::expect_true(all(data[[field]] == 0L), info = field)
      }
      black <- data[
        data$term == "black" & data$confidence_level == 0.95,
        ,
        drop = FALSE
      ]
      black <- black[
        order(black$city, as.integer(black$year), method = "radix"),
        ,
        drop = FALSE
      ]
      testthat::expect_equal(
        black$estimate,
        expected_black_estimates[[audit]],
        tolerance = 1e-12
      )
      testthat::expect_true(all(is.finite(
        unlist(
          black[c(
            "estimate",
            "std_error",
            "p_value",
            "conf_low",
            "conf_high"
          )],
          use.names = FALSE
        )
      )))
    }

    result_bytes <- lapply(result_paths, .regression_e2e_bytes)
    for (audit in names(regression_configs)) {
      process <- .regression_e2e_run_cli(
        "run_regression.R",
        regression_configs[[audit]]
      )
      testthat::expect_identical(
        process$status,
        0L,
        info = paste(process$output, collapse = "\n")
      )
      testthat::expect_identical(
        .regression_e2e_bytes(result_paths[[audit]]),
        result_bytes[[audit]]
      )
    }
    testthat::expect_identical(
      nrow(read_regression_results(unname(result_paths))),
      48L
    )

    # Rendering is a separate fresh process and depends only on saved results.
    testthat::expect_true(all(file.remove(unname(prepared_paths))))
    unlink(fixture_directory, recursive = TRUE, force = TRUE)
    testthat::expect_false(dir.exists(fixture_directory))

    render_config <- file.path(example_directory, "render_audits.yaml")
    process <- .regression_e2e_run_cli(
      "render_regression_plot.R",
      render_config
    )
    diagnostic <- paste(process$output, collapse = "\n")
    testthat::expect_identical(process$status, 0L, info = diagnostic)
    testthat::expect_match(
      diagnostic,
      "Rendered 8 coefficient(s) across 2 panel(s)",
      fixed = TRUE
    )

    figure_path <- file.path(
      output_root,
      "multi_audit_black_coefficients.png"
    )
    testthat::expect_true(file.exists(figure_path))
    testthat::expect_gt(file.info(figure_path)$size, 0)
    testthat::expect_equal(
      .regression_e2e_png_dimensions(figure_path),
      c(width = 1200, height = 600)
    )
    prepared_plot <- prepare_regression_plot_data(render_config)
    testthat::expect_identical(nrow(prepared_plot$data), 8L)
    testthat::expect_identical(
      prepared_plot$panel_order,
      unname(audit_ids)
    )
    testthat::expect_identical(
      prepared_plot$series_order,
      c("Montreal", "Toronto")
    )
    testthat::expect_identical(
      prepared_plot$period_order,
      c("2010", "2020")
    )
    testthat::expect_true(
      all(as.integer(table(prepared_plot$data$.plot_panel)) == 4L)
    )
    testthat::expect_false(
      file.exists(file.path(caller_directory, "Rplots.pdf"))
    )
  }
)
