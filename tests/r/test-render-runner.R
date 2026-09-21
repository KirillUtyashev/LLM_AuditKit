.render_runner_case <- function(output_path = "figures/callback.png") {
  directory <- tempfile("render-runner-")
  dir.create(directory, recursive = TRUE)
  input_path <- file.path(directory, "saved_results.csv")
  if (!file.copy(regression_fixture("render_results_synthetic.csv"), input_path)) {
    stop("Could not copy the synthetic saved-results fixture.")
  }
  config_path <- file.path(directory, "render.yaml")
  writeLines(c(
    "results_paths: [saved_results.csv]",
    sprintf("output_path: '%s'", gsub("'", "''", output_path, fixed = TRUE)),
    "term: black",
    "period_variable: period",
    "panel_variable: audit_id",
    "outcome_by_panel:",
    "  audit_a: pick_top",
    "  audit_b: pick_threshold",
    "  audit_c: pick_threshold",
    "  audit_d: pick_threshold",
    "width: 4",
    "height: 3",
    "dpi: 60"
  ), config_path, useBytes = TRUE)
  list(
    directory = directory,
    input_path = input_path,
    config_path = config_path,
    config = load_render_config(config_path)
  )
}

.render_runner_bytes <- function(path) {
  readBin(path, "raw", n = file.info(path)$size)
}

.render_runner_png_dimensions <- function(path) {
  header <- readBin(path, "raw", n = 24L)
  signature <- as.raw(c(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a))
  stopifnot(
    length(header) == 24L,
    identical(header[seq_len(8L)], signature),
    identical(rawToChar(header[13:16]), "IHDR")
  )
  # PNG stores the two unsigned dimensions in network (big-endian) order.
  c(
    width = sum(as.integer(header[17:20]) * 256^(3:0)),
    height = sum(as.integer(header[21:24]) * 256^(3:0))
  )
}

.render_runner_temporary_files <- function(config) {
  list.files(
    dirname(config$resolved_output_path),
    pattern = "^\\..*\\.tmp$", all.files = TRUE
  )
}

.render_runner_isolated_writer <- function(...) {
  writer <- .render_write_png_atomic
  injected <- list(...)
  isolated <- new.env(parent = environment(writer))
  for (name in names(injected)) {
    assign(name, injected[[name]], envir = isolated)
  }
  environment(writer) <- isolated
  writer
}

.render_runner_process_status <- function(output) {
  status <- attr(output, "status", exact = TRUE)
  if (is.null(status)) 0L else status
}

testthat::test_that("renderer writes and replaces valid PNGs with exact configured dimensions", {
  case <- .render_runner_case()
  original_input <- .render_runner_bytes(case$input_path)
  before_devices <- grDevices::dev.list()
  testthat::expect_false(dir.exists(dirname(case$config$resolved_output_path)))
  testthat::expect_message(
    prepared <- render_regression_plot(case$config_path),
    "Rendered 24 coefficient\\(s\\) across 4 panel\\(s\\).*240 x 180 pixels"
  )
  testthat::expect_s3_class(prepared, "regression_plot_data")
  testthat::expect_identical(nrow(prepared$data), 24L)
  testthat::expect_equal(
    .render_runner_png_dimensions(case$config$resolved_output_path),
    c(width = 240, height = 180)
  )
  testthat::expect_identical(grDevices::dev.list(), before_devices)
  testthat::expect_length(.render_runner_temporary_files(case$config), 0L)
  testthat::expect_identical(.render_runner_bytes(case$input_path), original_input)

  case$config$width <- 5
  testthat::expect_message(
    render_regression_plot(case$config), "300 x 180 pixels"
  )
  testthat::expect_equal(
    .render_runner_png_dimensions(case$config$resolved_output_path),
    c(width = 300, height = 180)
  )
  testthat::expect_identical(grDevices::dev.list(), before_devices)
  testthat::expect_length(.render_runner_temporary_files(case$config), 0L)
})

testthat::test_that("PNG output paths treat percent signs and format directives literally", {
  for (relative_path in c(
    "figures/figure%d.png",
    "figures/literal%20.png",
    "directorypercent%/figure.png",
    "directory%d/figure%02d.png",
    "directory%%/figure%%.png"
  )) {
    case <- .render_runner_case(relative_path)
    before_devices <- grDevices::dev.list()
    testthat::expect_message(render_regression_plot(case$config_path), "Rendered 24 coefficient")
    testthat::expect_equal(
      .render_runner_png_dimensions(case$config$resolved_output_path),
      c(width = 240, height = 180)
    )
    expected_files <- c("saved_results.csv", "render.yaml", relative_path)
    testthat::expect_setequal(
      list.files(case$directory, recursive = TRUE, all.files = TRUE), expected_files
    )
    testthat::expect_length(.render_runner_temporary_files(case$config), 0L)
    testthat::expect_identical(grDevices::dev.list(), before_devices)

    # Device cleanup must also use the literal path after a partially drawn page.
    previous <- .render_runner_bytes(case$config$resolved_output_path)
    writer <- .render_runner_isolated_writer(print = function(...) {
      graphics::plot(c(0, 1), c(0, 1))
      stop("injected print failure", call. = FALSE)
    })
    testthat::expect_error(writer(NULL, case$config), "Could not render PNG: injected print failure")
    testthat::expect_identical(.render_runner_bytes(case$config$resolved_output_path), previous)
    testthat::expect_setequal(
      list.files(case$directory, recursive = TRUE, all.files = TRUE), expected_files
    )
    testthat::expect_identical(grDevices::dev.list(), before_devices)
  }
})

testthat::test_that("validation failure leaves an existing artifact and devices unchanged", {
  case <- .render_runner_case()
  dir.create(dirname(case$config$resolved_output_path))
  writeBin(charToRaw("prior user artifact"), case$config$resolved_output_path)
  previous <- .render_runner_bytes(case$config$resolved_output_path)
  before_devices <- grDevices::dev.list()
  case$config$term <- "not_an_estimated_coefficient"

  testthat::expect_error(
    render_regression_plot(case$config),
    "term and confidence-level selection.*audit_id='audit_a'"
  )
  testthat::expect_identical(.render_runner_bytes(case$config$resolved_output_path), previous)
  testthat::expect_identical(grDevices::dev.list(), before_devices)
  testthat::expect_length(.render_runner_temporary_files(case$config), 0L)
})

testthat::test_that("an output-directory creation failure does not touch the blocking file", {
  case <- .render_runner_case()
  blocking_path <- dirname(case$config$resolved_output_path)
  writeBin(charToRaw("unrelated file"), blocking_path)
  previous <- .render_runner_bytes(blocking_path)
  before_devices <- grDevices::dev.list()
  testthat::expect_error(
    render_regression_plot(case$config), "Could not create PNG output directory"
  )
  testthat::expect_identical(.render_runner_bytes(blocking_path), previous)
  testthat::expect_identical(grDevices::dev.list(), before_devices)
})

testthat::test_that("print errors and warnings clean up only the renderer's graphics device", {
  case <- .render_runner_case()
  dir.create(dirname(case$config$resolved_output_path))
  writeBin(charToRaw("prior user artifact"), case$config$resolved_output_path)
  previous <- .render_runner_bytes(case$config$resolved_output_path)

  # A caller-owned device must remain open when the temporary render fails.
  grDevices::png(file.path(case$directory, "caller.png"), width = 240, height = 180)
  caller_device <- grDevices::dev.cur()
  on.exit({
    if (caller_device %in% grDevices::dev.list()) grDevices::dev.off(caller_device)
  }, add = TRUE)
  before_devices <- grDevices::dev.list()

  for (failure in c("error", "warning")) {
    broken_print <- local({
      mode <- failure
      function(...) {
        if (mode == "warning") warning("injected print failure", call. = FALSE)
        else stop("injected print failure", call. = FALSE)
      }
    })
    writer <- .render_runner_isolated_writer(print = broken_print)
    testthat::expect_error(
      writer(NULL, case$config), "Could not render PNG: injected print failure"
    )
    testthat::expect_identical(.render_runner_bytes(case$config$resolved_output_path), previous)
    testthat::expect_identical(grDevices::dev.list(), before_devices)
    testthat::expect_identical(grDevices::dev.cur(), caller_device)
    testthat::expect_length(.render_runner_temporary_files(case$config), 0L)
  }
})

testthat::test_that("atomic rename failures preserve old output and remove the temporary PNG", {
  case <- .render_runner_case()
  dir.create(dirname(case$config$resolved_output_path))
  writeBin(charToRaw("prior user artifact"), case$config$resolved_output_path)
  previous <- .render_runner_bytes(case$config$resolved_output_path)
  before_devices <- grDevices::dev.list()
  observed <- new.env(parent = emptyenv())
  writer <- .render_runner_isolated_writer(
    print = function(...) graphics::plot(c(0, 1), c(0, 1)),
    file.rename = function(from, to) {
      observed$from <- from
      observed$to <- to
      observed$dimensions <- .render_runner_png_dimensions(from)
      observed$devices <- grDevices::dev.list()
      FALSE
    }
  )

  testthat::expect_error(writer(NULL, case$config), "Could not atomically replace PNG")
  testthat::expect_identical(observed$to, case$config$resolved_output_path)
  testthat::expect_identical(dirname(observed$from), dirname(case$config$resolved_output_path))
  testthat::expect_equal(observed$dimensions, c(width = 240, height = 180))
  testthat::expect_identical(observed$devices, before_devices)
  testthat::expect_false(file.exists(observed$from))
  testthat::expect_identical(.render_runner_bytes(case$config$resolved_output_path), previous)
  testthat::expect_identical(grDevices::dev.list(), before_devices)
  testthat::expect_length(.render_runner_temporary_files(case$config), 0L)
})

testthat::test_that("render CLI argument parsing accepts exactly one --config pair", {
  testthat::expect_identical(
    .render_parse_cli_args(c("--config", "render.yaml")), "render.yaml"
  )
  for (invalid in list(
    character(), "render.yaml", "--config", c("--config", ""),
    c("--config", NA_character_), c("--unknown", "render.yaml"),
    c("--config", "render.yaml", "extra"), c("--config=render.yaml")
  )) {
    testthat::expect_error(
      .render_parse_cli_args(invalid),
      "Usage: Rscript scripts/render_regression_plot.R --config <path>",
      fixed = TRUE
    )
  }
})

testthat::test_that("render CLI recreates a PNG from copied CSV and YAML outside the repository", {
  case <- .render_runner_case()
  caller_directory <- file.path(case$directory, "caller")
  dir.create(caller_directory)
  previous <- setwd(caller_directory)
  on.exit(setwd(previous), add = TRUE)
  script <- file.path(REGRESSION_PROJECT_ROOT, "scripts", "render_regression_plot.R")
  output <- system2(
    file.path(R.home("bin"), "Rscript"),
    c("--vanilla", shQuote(script), "--config", shQuote(case$config_path)),
    stdout = TRUE, stderr = TRUE
  )
  testthat::expect_identical(.render_runner_process_status(output), 0L)
  testthat::expect_match(paste(output, collapse = "\n"), "Rendered 24 coefficient")
  testthat::expect_equal(
    .render_runner_png_dimensions(case$config$resolved_output_path),
    c(width = 240, height = 180)
  )
  testthat::expect_false(file.exists(file.path(caller_directory, "figures", "callback.png")))
  testthat::expect_false(file.exists(file.path(caller_directory, "Rplots.pdf")))
  testthat::expect_length(.render_runner_temporary_files(case$config), 0L)

  for (arguments in list(character(), c("--unknown", shQuote(case$config_path)))) {
    failure <- suppressWarnings(system2(
      file.path(R.home("bin"), "Rscript"),
      c("--vanilla", shQuote(script), arguments), stdout = TRUE, stderr = TRUE
    ))
    testthat::expect_identical(.render_runner_process_status(failure), 1L)
    testthat::expect_match(
      paste(failure, collapse = "\n"),
      "Usage: Rscript scripts/render_regression_plot.R --config <path>",
      fixed = TRUE
    )
  }

  prior_png <- .render_runner_bytes(case$config$resolved_output_path)
  writeLines(c(readLines(case$config_path), "unknown_setting: true"), case$config_path)
  failure <- suppressWarnings(system2(
    file.path(R.home("bin"), "Rscript"),
    c("--vanilla", shQuote(script), "--config", shQuote(case$config_path)),
    stdout = TRUE, stderr = TRUE
  ))
  testthat::expect_identical(.render_runner_process_status(failure), 1L)
  testthat::expect_match(paste(failure, collapse = "\n"), "unknown field.*unknown_setting")
  testthat::expect_identical(.render_runner_bytes(case$config$resolved_output_path), prior_png)
})

testthat::test_that("a fresh rendering-only R process does not load the estimator namespace", {
  case <- .render_runner_case()
  caller_directory <- file.path(case$directory, "caller")
  dir.create(caller_directory)
  previous <- setwd(caller_directory)
  on.exit(setwd(previous), add = TRUE)
  code <- paste0(
    "project <- ", encodeString(REGRESSION_PROJECT_ROOT, quote = '"'), "; ",
    "Sys.setenv(RENV_PROJECT = project); ",
    "source(file.path(project, 'renv', 'activate.R')); ",
    "for (module in c('regression_config', 'render_config', 'render_data', ",
    "'paper_plot', 'render_runner')) ",
    "source(file.path(project, 'R', 'regression', paste0(module, '.R'))); ",
    "stopifnot(!'fixest' %in% loadedNamespaces(), ",
    "!exists('estimate_regressions', inherits = FALSE)); ",
    "render_regression_plot(", encodeString(case$config_path, quote = '"'), "); ",
    "stopifnot(!'fixest' %in% loadedNamespaces(), ",
    "!exists('estimate_regressions', inherits = FALSE), is.null(grDevices::dev.list())); ",
    "cat('Rendering completed without loading fixest.\\n')"
  )
  output <- system2(
    file.path(R.home("bin"), "Rscript"),
    c("--vanilla", "-e", shQuote(code)), stdout = TRUE, stderr = TRUE
  )
  testthat::expect_identical(.render_runner_process_status(output), 0L)
  testthat::expect_match(
    paste(output, collapse = "\n"), "Rendering completed without loading fixest.",
    fixed = TRUE
  )
  testthat::expect_equal(
    .render_runner_png_dimensions(case$config$resolved_output_path),
    c(width = 240, height = 180)
  )
  testthat::expect_false(file.exists(file.path(caller_directory, "Rplots.pdf")))
})
