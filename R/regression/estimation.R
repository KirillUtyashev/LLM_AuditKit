REGRESSION_CONFIDENCE_LEVELS <- c(0.90, 0.95, 0.99)
REGRESSION_ESTIMATOR <- "fixest::feols"
REGRESSION_INFERENCE_CONTRACT_ID <- "fixest_feols_ssc_v1"

.regression_locked_ssc <- function() {
  fixest::ssc(
    K.adj = TRUE,
    K.fixef = "nonnested",
    K.exact = FALSE,
    G.adj = TRUE,
    G.df = "min",
    t.df = "min"
  )
}

.regression_group_rows <- function(data, variables) {
  if (length(variables) == 0L) {
    return(list(seq_len(nrow(data))))
  }
  order_arguments <- c(
    unname(data[variables]),
    list(na.last = TRUE, method = "radix")
  )
  ordered_rows <- do.call(order, order_arguments)
  boundaries <- rep(FALSE, max(nrow(data) - 1L, 0L))
  if (length(boundaries) > 0L) {
    for (field in variables) {
      values <- data[[field]][ordered_rows]
      boundaries <- boundaries | values[-1L] != values[-length(values)]
    }
  }
  starts <- c(1L, which(boundaries) + 1L)
  ends <- c(which(boundaries), length(ordered_rows))
  Map(
    function(start, end) ordered_rows[seq.int(start, end)],
    starts,
    ends
  )
}

.regression_group_label <- function(data, config) {
  if (length(config$estimation_group_variables) == 0L) {
    return("full dataset")
  }
  paste(
    sprintf(
      "%s=%s",
      config$estimation_group_variables,
      unlist(
        data[1L, config$estimation_group_variables, drop = FALSE],
        use.names = FALSE
      )
    ),
    collapse = ", "
  )
}

.regression_complete_rows <- function(data, variables) {
  complete <- rep(TRUE, nrow(data))
  for (field in variables) {
    values <- data[[field]]
    present <- !is.na(values)
    if (is.character(values)) {
      present <- present & nzchar(trimws(values))
    }
    if (is.numeric(values)) {
      present <- present & is.finite(values)
    }
    complete <- complete & present
  }
  complete
}

.regression_capture_warnings <- function(expression) {
  warnings <- character()
  value <- withCallingHandlers(
    expression,
    warning = function(warning) {
      warnings <<- c(warnings, conditionMessage(warning))
      invokeRestart("muffleWarning")
    }
  )
  list(value = value, warnings = unique(warnings))
}

.regression_fit_error <- function(group_label, format, ...) {
  stop(
    sprintf(
      "Regression fit failed for %s: %s",
      group_label,
      sprintf(format, ...)
    ),
    call. = FALSE
  )
}

.regression_cluster_counts <- function(data, variables, group_label) {
  if (length(variables) == 0L) {
    return("")
  }
  counts <- vapply(
    variables,
    function(field) length(unique(data[[field]])),
    integer(1)
  )
  insufficient <- counts < 2L
  if (any(insufficient)) {
    .regression_fit_error(
      group_label,
      "cluster variable '%s' has fewer than two used-sample clusters.",
      variables[which(insufficient)[[1L]]]
    )
  }
  paste(sprintf("%s=%d", variables, counts), collapse = "|")
}

.regression_validate_inference <- function(
  coefficient_table,
  intervals,
  group_label
) {
  numerical <- c(
    as.numeric(coefficient_table),
    unlist(intervals, use.names = FALSE)
  )
  if (any(!is.finite(numerical))) {
    .regression_fit_error(
      group_label,
      "coefficient or inference output is non-finite."
    )
  }
  invisible(coefficient_table)
}

.regression_fit_one_group <- function(data, config, provenance) {
  group_label <- .regression_group_label(data, config)
  n_input <- nrow(data)
  rhs <- c(config$explanatory_variables, config$control_variables)
  model_variables <- unique(c(
    config$outcome_variable,
    rhs,
    config$fixed_effects,
    config$cluster_variables
  ))
  complete_rows <- .regression_complete_rows(data, model_variables)
  complete <- data[complete_rows, , drop = FALSE]
  n_complete <- nrow(complete)
  if (n_complete == 0L) {
    .regression_fit_error(
      group_label,
      "no complete cases remain for the configured model variables."
    )
  }

  if (length(config$cluster_variables) > 0L) {
    .regression_cluster_counts(
      complete,
      config$cluster_variables,
      group_label
    )
  }

  formula <- stats::reformulate(
    termlabels = rhs,
    response = config$outcome_variable
  )
  vcov_specification <- if (length(config$cluster_variables) == 0L) {
    "iid"
  } else {
    fixest::vcov_cluster(
      cluster = config$cluster_variables,
      vcov_fix = TRUE
    )
  }
  fit_arguments <- list(
    fml = formula,
    data = complete,
    vcov = "iid",
    ssc = .regression_locked_ssc(),
    fixef.rm = "perfect_fit",
    fixef.tol = 1e-6,
    fixef.iter = 10000L,
    collin.tol = 1e-9,
    nthreads = 1L,
    lean = FALSE,
    data.save = FALSE,
    warn = TRUE,
    notes = FALSE
  )
  if (length(config$fixed_effects) > 0L) {
    fit_arguments$fixef <- config$fixed_effects
  }
  fit_attempt <- tryCatch(
    .regression_capture_warnings(
      do.call(fixest::feols, fit_arguments)
    ),
    error = function(error) {
      .regression_fit_error(group_label, "%s", conditionMessage(error))
    }
  )
  if (length(fit_attempt$warnings) > 0L) {
    .regression_fit_error(
      group_label,
      "fixest warning: %s",
      paste(fit_attempt$warnings, collapse = "; ")
    )
  }
  fit <- fit_attempt$value

  coefficient_names <- names(stats::coef(fit))
  removed_terms <- setdiff(rhs, coefficient_names)
  if (length(removed_terms) > 0L) {
    .regression_fit_error(
      group_label,
      "requested term(s) removed through collinearity: %s",
      paste(removed_terms, collapse = ", ")
    )
  }
  expected_terms <- if (length(config$fixed_effects) == 0L) {
    c("(Intercept)", rhs)
  } else {
    rhs
  }
  unexpected_terms <- setdiff(coefficient_names, expected_terms)
  missing_terms <- setdiff(expected_terms, coefficient_names)
  if (length(unexpected_terms) > 0L || length(missing_terms) > 0L) {
    .regression_fit_error(
      group_label,
      "estimated coefficient set does not match the configured specification."
    )
  }

  used_rows <- as.integer(fixest::obs(fit))
  n_used <- as.integer(stats::nobs(fit))
  if (length(used_rows) != n_used || n_used == 0L) {
    .regression_fit_error(
      group_label,
      "fixest returned an invalid used-observation set."
    )
  }
  used <- complete[used_rows, , drop = FALSE]
  cluster_counts <- .regression_cluster_counts(
    used,
    config$cluster_variables,
    group_label
  )
  if (length(config$cluster_variables) > 0L) {
    inference_attempt <- tryCatch(
      .regression_capture_warnings(
        summary(
          fit,
          vcov = vcov_specification,
          ssc = .regression_locked_ssc()
        )
      ),
      error = function(error) {
        .regression_fit_error(group_label, "%s", conditionMessage(error))
      }
    )
    if (length(inference_attempt$warnings) > 0L) {
      .regression_fit_error(
        group_label,
        "clustered-inference warning: %s",
        paste(inference_attempt$warnings, collapse = "; ")
      )
    }
    fit <- inference_attempt$value
  }

  table_attempt <- tryCatch(
    .regression_capture_warnings(fixest::coeftable(fit)),
    error = function(error) {
      .regression_fit_error(group_label, "%s", conditionMessage(error))
    }
  )
  if (length(table_attempt$warnings) > 0L) {
    .regression_fit_error(
      group_label,
      "coefficient inference warning: %s",
      paste(table_attempt$warnings, collapse = "; ")
    )
  }
  coefficient_table <- as.matrix(table_attempt$value)
  coefficient_table <- coefficient_table[expected_terms, , drop = FALSE]

  intervals <- lapply(
    REGRESSION_CONFIDENCE_LEVELS,
    function(level) {
      interval_attempt <- tryCatch(
        .regression_capture_warnings(
          stats::confint(
            fit,
            parm = expected_terms,
            level = level
          )
        ),
        error = function(error) {
          .regression_fit_error(group_label, "%s", conditionMessage(error))
        }
      )
      if (length(interval_attempt$warnings) > 0L) {
        .regression_fit_error(
          group_label,
          "confidence-interval warning: %s",
          paste(interval_attempt$warnings, collapse = "; ")
        )
      }
      interval <- as.matrix(interval_attempt$value)
      interval[expected_terms, , drop = FALSE]
    }
  )
  .regression_validate_inference(
    coefficient_table,
    intervals,
    group_label
  )

  n_missing_dropped <- as.integer(n_input - n_complete)
  n_estimator_dropped <- as.integer(n_complete - n_used)
  n_dropped <- as.integer(n_input - n_used)
  fit_rows <- vector("list", length(expected_terms) * 3L)
  row_index <- 1L
  for (term_index in seq_along(expected_terms)) {
    for (level_index in seq_along(REGRESSION_CONFIDENCE_LEVELS)) {
      fit_rows[[row_index]] <- data.frame(
        dataset_id = config$dataset_id,
        model_id = config$model_id,
        estimator = REGRESSION_ESTIMATOR,
        estimator_version = as.character(
          utils::packageVersion("fixest")
        ),
        inference_contract_id = REGRESSION_INFERENCE_CONTRACT_ID,
        outcome_variable = config$outcome_variable,
        term = expected_terms[[term_index]],
        estimate = unname(coefficient_table[term_index, 1L]),
        std_error = unname(coefficient_table[term_index, 2L]),
        statistic = unname(coefficient_table[term_index, 3L]),
        p_value = unname(coefficient_table[term_index, 4L]),
        n_input = as.integer(n_input),
        n_complete = as.integer(n_complete),
        n_used = n_used,
        n_missing_dropped = n_missing_dropped,
        n_estimator_dropped = n_estimator_dropped,
        n_dropped = n_dropped,
        confidence_level = REGRESSION_CONFIDENCE_LEVELS[[level_index]],
        conf_low = unname(intervals[[level_index]][term_index, 1L]),
        conf_high = unname(intervals[[level_index]][term_index, 2L]),
        vcov_type = if (length(config$cluster_variables) == 0L) {
          "iid"
        } else {
          "cluster"
        },
        explanatory_variables = paste(
          config$explanatory_variables,
          collapse = "|"
        ),
        control_variables = paste(config$control_variables, collapse = "|"),
        fixed_effects = paste(config$fixed_effects, collapse = "|"),
        cluster_variables = paste(
          config$cluster_variables,
          collapse = "|"
        ),
        estimation_group_variables = paste(
          config$estimation_group_variables,
          collapse = "|"
        ),
        cluster_counts = cluster_counts,
        preparation_top_share = provenance$preparation_top_share,
        preparation_probability_threshold =
          provenance$preparation_probability_threshold,
        preparation_ranking_group_variables =
          provenance$preparation_ranking_group_variables,
        preparation_scenario_covariates =
          provenance$preparation_scenario_covariates,
        preparation_candidate_covariates =
          provenance$preparation_candidate_covariates,
        check.names = FALSE,
        stringsAsFactors = FALSE
      )
      for (field in config$estimation_group_variables) {
        fit_rows[[row_index]][[field]] <- data[[field]][[1L]]
      }
      row_index <- row_index + 1L
    }
  }
  do.call(rbind, fit_rows)
}

estimate_regressions <- function(config) {
  config <- .regression_as_config(config)
  if (!requireNamespace("fixest", quietly = TRUE)) {
    stop(
      "Package 'fixest' is required to estimate regressions.",
      call. = FALSE
    )
  }
  data <- load_regression_data(config)
  provenance <- attr(data, "preparation_provenance", exact = TRUE)
  groups <- .regression_group_rows(
    data,
    config$estimation_group_variables
  )
  results <- do.call(
    rbind,
    lapply(
      groups,
      function(rows) {
        .regression_fit_one_group(
          data[rows, , drop = FALSE],
          config,
          provenance
        )
      }
    )
  )
  row.names(results) <- NULL
  results <- results[c(
    REGRESSION_RESULT_CORE_COLUMNS,
    config$estimation_group_variables
  )]
  attr(results, "regression_fit_count") <- as.integer(length(groups))
  results
}
