auditkit_fixture <- function(n = 3L) {
  data <- data.frame(
    experiment_id = c("experiment-a", "experiment-a"),
    scenario_id = c("001", "002"), persona_id = "reviewer-a",
    model_config_id = "model-a", request_id = c("request-a", "request-b"),
    candidate_count = as.character(n), city = "SyntheticCity", year = "2010",
    error_type = c("", "ProviderError"), error_message = c("", "synthetic failure"),
    user_prompt = "private prompt", generated_response = "private response",
    stringsAsFactors = FALSE
  )
  for (slot in seq_len(n)) {
    data[[sprintf("candidate_%d_id", slot)]] <- c(
      sprintf("assigned-person-a-%d", slot), sprintf("assigned-person-b-%d", slot)
    )
    data[[sprintf("candidate_%d_treatment", slot)]] <- as.character(slot %% 2L)
    data[[paste0("pick", slot)]] <- c(as.character(slot %% 2L), "")
    data[[paste0("logprob", slot)]] <- c(as.character(log(0.995)), "")
  }
  data
}

auditkit_config <- function(data) {
  path <- tempfile(fileext = ".csv")
  utils::write.csv(data, path, row.names = FALSE, na = "")
  write_test_config(
    path, tempfile(fileext = ".csv"),
    c("input_format: auditkit", "candidate_covariates: [treatment]")
  )
}

testthat::test_that("native AuditKit jobs prepare with variable N and unchanged identities/probabilities", {
  for (n in c(1L, 3L, 12L)) {
    native <- auditkit_fixture(n)
    config <- auditkit_config(native)
    loaded <- load_experiment_results(config)
    testthat::expect_identical(loaded$scenario_id, c("001", "002"))
    testthat::expect_identical(loaded$result_status, c("completed", "failed"))
    testthat::expect_identical(loaded$candidate_1_log_probability, native$logprob1)
    testthat::expect_warning(
      prepared <- prepare_regression_data(config), "excluded 1 non-completed input job"
    )
    # Preparation orders by stable identity, not applicant position. Inspect
    # the explicit slot association when checking N >= 10.
    prepared <- prepared[order(prepared$candidate_index), , drop = FALSE]
    testthat::expect_equal(nrow(prepared), n)
    testthat::expect_identical(prepared$scenario_id, rep("001", n))
    testthat::expect_identical(prepared$candidate_id, sprintf("assigned-person-a-%d", seq_len(n)))
    testthat::expect_equal(prepared$pick, seq_len(n) %% 2L)
    testthat::expect_identical(prepared$treatment, as.character(seq_len(n) %% 2L))
    testthat::expect_equal(prepared$log_probability, rep(log(0.995), n))
    testthat::expect_identical(unique(prepared$audit_id), "test_audit")
    testthat::expect_false(any(c("user_prompt", "generated_response", "error_message") %in% names(prepared)))
  }
})

testthat::test_that("AuditKit failure classification uses either error field", {
  for (field in c("error_type", "error_message")) {
    native <- auditkit_fixture()
    native[[field]][2L] <- ""
    loaded <- load_experiment_results(auditkit_config(native))
    testthat::expect_identical(loaded$result_status, c("completed", "failed"))
  }
})

testthat::test_that("AuditKit normalization rejects ambiguous and incomplete schemas", {
  for (field in c("result_status", "candidate_1_pick", "candidate_1_log_probability")) {
    native <- auditkit_fixture()
    native[[field]] <- ""
    testthat::expect_error(load_experiment_results(auditkit_config(native)), "must not also contain canonical")
  }
  for (field in c("experiment_id", "request_id", "error_type", "error_message", "candidate_count", "city")) {
    native <- auditkit_fixture()
    native[[field]] <- NULL
    testthat::expect_error(load_experiment_results(auditkit_config(native)), paste0("missing.*", field))
  }
  for (field in c("experiment_id", "request_id")) {
    native <- auditkit_fixture()
    native[[field]][1L] <- ""
    testthat::expect_error(load_experiment_results(auditkit_config(native)), paste0("column '", field, "' is empty"))
  }
  for (field in c("pick2", "logprob2")) {
    native <- auditkit_fixture()
    native[[field]] <- NULL
    testthat::expect_error(load_experiment_results(auditkit_config(native)), "pick/logprob families")
  }
  native <- auditkit_fixture()
  native$pick4 <- ""
  testthat::expect_error(load_experiment_results(auditkit_config(native)), "pick/logprob families")
})

testthat::test_that("AuditKit preparation never invents candidate IDs or repairs successful results", {
  native <- auditkit_fixture()
  native$candidate_1_id[1L] <- ""
  testthat::expect_error(prepare_regression_data(auditkit_config(native)), "empty stable ID")
  native <- auditkit_fixture()
  native$pick1[1L] <- ""
  testthat::expect_error(suppressWarnings(prepare_regression_data(auditkit_config(native))), "pick")
})

testthat::test_that("native audits reject mixed experiments, personas and model configurations", {
  for (field in c("experiment_id", "persona_id", "model_config_id")) {
    native <- auditkit_fixture()
    native[[field]][2L] <- "other-value"
    testthat::expect_error(load_experiment_results(auditkit_config(native)), paste0("spans multiple ", field))
  }
})
