if (!file.exists(file.path("tests", "r", "run_tests.R"))) {
  stop("Run this command from the repository root.", call. = FALSE)
}

testthat::test_dir(
  file.path("tests", "r"),
  reporter = "summary",
  stop_on_failure = TRUE,
  stop_on_warning = TRUE
)
