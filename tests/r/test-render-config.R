source(
  file.path(REGRESSION_PROJECT_ROOT, "R", "regression", "render_config.R"),
  local = TRUE
)

.render_config_test_lines <- function() {
  c(
    "results_paths: [one.csv]",
    "output_path: output/figure.png",
    "term: black",
    "period_variable: period",
    "panel_variable: model_config_id"
  )
}

.write_render_config_test <- function(lines = .render_config_test_lines()) {
  directory <- tempfile("render-config-")
  dir.create(directory, recursive = TRUE)
  writeLines("term,estimate\nblack,-0.1", file.path(directory, "one.csv"))
  writeLines("term,estimate\nblack,-0.2", file.path(directory, "two.csv"))
  path <- file.path(directory, "render.yaml")
  writeLines(lines, path, useBytes = TRUE)
  path
}

.render_config_test_replace <- function(field, value) {
  lines <- .render_config_test_lines()
  prefix <- paste0(field, ":")
  replacement <- paste0(prefix, " ", value)
  if (any(startsWith(lines, prefix))) {
    lines[startsWith(lines, prefix)] <- replacement
    lines
  } else {
    c(lines, replacement)
  }
}

testthat::test_that("minimal render config exposes exact keys and defaults", {
  path <- .write_render_config_test()
  previous <- setwd(tempdir())
  on.exit(setwd(previous), add = TRUE)
  config <- load_render_config(path)

  testthat::expect_s3_class(config, "render_config")
  testthat::expect_identical(
    RENDER_CONFIG_KEYS,
    c(
      "results_paths", "output_path", "term", "confidence_level",
      "period_variable", "series_variable", "panel_variable", "outcome_by_panel",
      "period_order", "series_order", "panel_order", "panel_labels", "x_label",
      "y_label", "y_limits", "y_break_interval", "significance_level",
      "panel_columns", "width", "height", "dpi"
    )
  )
  testthat::expect_identical(
    names(config),
    c(RENDER_CONFIG_KEYS, "config_path", "config_directory",
      "resolved_results_paths", "resolved_output_path")
  )
  testthat::expect_identical(config$results_paths, "one.csv")
  testthat::expect_identical(config$output_path, "output/figure.png")
  testthat::expect_identical(config$term, "black")
  testthat::expect_identical(config$confidence_level, 0.95)
  testthat::expect_identical(config$period_variable, "period")
  testthat::expect_identical(config$panel_variable, "model_config_id")
  testthat::expect_null(config$series_variable)
  for (field in c(
    "outcome_by_panel", "period_order", "series_order", "panel_order", "panel_labels"
  )) {
    testthat::expect_identical(config[[field]], character())
  }
  testthat::expect_identical(config$x_label, "Period")
  testthat::expect_identical(config$y_label, "Coefficient estimate")
  testthat::expect_identical(config$y_limits, c(-0.3, 0.3))
  testthat::expect_identical(config$y_break_interval, 0.1)
  testthat::expect_identical(config$significance_level, 0.05)
  testthat::expect_identical(config$panel_columns, 2L)
  testthat::expect_identical(config$width, 12)
  testthat::expect_identical(config$height, 8)
  testthat::expect_identical(config$dpi, 300L)
  testthat::expect_identical(config$config_path, normalizePath(path))
  testthat::expect_identical(config$config_directory, dirname(normalizePath(path)))
  testthat::expect_identical(
    config$resolved_results_paths, file.path(dirname(normalizePath(path)), "one.csv")
  )
  testthat::expect_identical(
    config$resolved_output_path,
    file.path(dirname(normalizePath(path)), "output", "figure.png")
  )
  testthat::expect_false(dir.exists(dirname(config$resolved_output_path)))
  testthat::expect_identical(.render_as_config(config), config)
  testthat::expect_identical(.render_as_config(path), config)
})

testthat::test_that("explicit render settings preserve orders and named maps", {
  path <- .write_render_config_test(c(
    .render_config_test_replace("results_paths", "[two.csv, ./one.csv]"),
    "confidence_level: 0.99",
    "series_variable: city",
    "outcome_by_panel: {model-b: pick_threshold, model-a: pick_top}",
    "period_order: [2020, 1970, '1980']",
    "series_order: [Toronto, Montreal]",
    "panel_order: [model-b, model-a]",
    "panel_labels: {model-b: 'Panel A: Model B'}",
    "x_label: Survey year",
    "y_label: Black coefficient",
    "y_limits: [-0.6, 0.2]",
    "y_break_interval: 0.2",
    "significance_level: 0.1",
    "panel_columns: 1",
    "width: 10",
    "height: 4.5",
    "dpi: 150"
  ))
  config <- load_render_config(path)
  testthat::expect_identical(config$results_paths, c("two.csv", "one.csv"))
  testthat::expect_identical(config$period_order, c("2020", "1970", "1980"))
  testthat::expect_identical(config$series_order, c("Toronto", "Montreal"))
  testthat::expect_identical(config$panel_order, c("model-b", "model-a"))
  testthat::expect_identical(
    config$outcome_by_panel, c("model-b" = "pick_threshold", "model-a" = "pick_top")
  )
  testthat::expect_identical(config$panel_labels, c("model-b" = "Panel A: Model B"))
  testthat::expect_identical(config$confidence_level, 0.99)
  testthat::expect_identical(config$y_limits, c(-0.6, 0.2))
  testthat::expect_identical(config$panel_columns, 1L)
  testthat::expect_identical(config$width, 10)
  testthat::expect_identical(config$height, 4.5)
  testthat::expect_identical(config$dpi, 150L)

  logical_order <- load_render_config(.write_render_config_test(c(
    .render_config_test_lines(),
    "panel_order: [true, false]",
    "panel_labels: {true: Selected, false: Unselected}"
  )))
  testthat::expect_identical(logical_order$panel_order, c("TRUE", "FALSE"))
  testthat::expect_identical(
    logical_order$panel_labels, c("TRUE" = "Selected", "FALSE" = "Unselected")
  )
  testthat::expect_identical(
    load_render_config(.write_render_config_test(
      .render_config_test_replace("term", "'(Intercept)'")))$term,
    "(Intercept)"
  )
})

testthat::test_that("render config rejects missing fields and malformed YAML", {
  for (invalid in list(NULL, NA_character_, character(), c("a", "b"), " ", 1)) {
    testthat::expect_error(load_render_config(invalid), "path must be one nonempty string")
  }
  testthat::expect_error(load_render_config(tempfile()), "file does not exist")
  testthat::expect_error(load_render_config(tempdir()), "file does not exist")
  testthat::expect_error(.render_as_config(list()), "render_config or one YAML")
  for (invalid in c("[]", "null", "scalar", "- one")) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(invalid)),
      "top level must be a YAML mapping"
    )
  }
  testthat::expect_error(
    load_render_config(.write_render_config_test("{}")), "missing required field"
  )
  testthat::expect_error(
    load_render_config(.write_render_config_test(c(
      .render_config_test_lines(), "typo: true"))),
    "unknown field.*typo"
  )
  for (field in c("results_paths", "output_path", "term", "period_variable", "panel_variable")) {
    lines <- .render_config_test_lines()
    testthat::expect_error(
      load_render_config(.write_render_config_test(lines[!startsWith(lines, paste0(field, ":"))])),
      paste0("missing required field.*", field)
    )
  }
  testthat::expect_error(
    load_render_config(.write_render_config_test("results_paths: [")),
    "YAML could not be parsed"
  )
  testthat::expect_error(
    load_render_config(.write_render_config_test(c(
      .render_config_test_lines(), "term: high"))),
    "YAML could not be parsed.*Duplicate map key"
  )
})

testthat::test_that("render strings, literal columns and dimensions are strict", {
  for (field in c("output_path", "term", "period_variable", "panel_variable", "x_label", "y_label")) {
    for (invalid in c("null", "''", "' '", "123", "true", "[black]", "{}")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        paste0(field, ".*one nonempty string")
      )
    }
  }
  for (field in c("period_variable", "panel_variable", "series_variable")) {
    for (invalid in c("'year + city'", "if", "'bad-name'", "'a.b'", "'1year'")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        paste0(field, ".*invalid column name")
      )
    }
  }
  for (pair in list(c("panel_variable", "period"), c("series_variable", "period"),
                    c("series_variable", "model_config_id"))) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace(pair[1], pair[2]))),
      "must be distinct"
    )
  }
  testthat::expect_error(
    load_render_config(.write_render_config_test(.render_config_test_replace("series_order", "[Toronto]"))),
    "series_order.*must be.*series_variable.*null"
  )
})

testthat::test_that("render lists and maps reject ambiguous shapes and duplicate values", {
  for (invalid in c("one.csv", "[]", "{}", "null", "[1]", "[true]", "[null]", "['']", "[[one.csv]]")) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace("results_paths", invalid))),
      "results_paths"
    )
  }
  for (field in c("period_order", "panel_order", "series_order")) {
    for (invalid in c("1970", "{}", "null", "[null]", "[.inf]", "[.nan]", "[' ']",
                      "[[1970]]", "[{year: 1970}]", "[1970, '1970']", "[true, 'TRUE']")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        field
      )
    }
  }
  for (field in c("panel_labels", "outcome_by_panel")) {
    for (invalid in c("[]", "null", "[x]", "label", "{x: 1}", "{x: true}", "{x: null}",
                      "{x: ''}", "{' ': label}", "{x: [label]}", "{x: {y: label}}")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        field
      )
    }
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace(field, "{x: a, x: b}"))),
      "Duplicate map key"
    )
    testthat::expect_identical(
      load_render_config(.write_render_config_test(.render_config_test_replace(field, "{}")))[[field]],
      character()
    )
  }
})

testthat::test_that("render numeric settings enforce finite numeric ranges", {
  fields <- c("confidence_level", "y_break_interval", "significance_level", "panel_columns", "width", "height", "dpi")
  for (field in fields) {
    for (invalid in c("null", "'1'", "true", "[1]", "{}", ".inf", "-.inf", ".nan")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        paste0(field, ".*one finite number")
      )
    }
  }
  for (invalid in c("0.5", "0.949999999", "1")) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace("confidence_level", invalid))),
      "confidence_level.*one of"
    )
  }
  for (field in c("y_break_interval", "panel_columns", "width", "height", "dpi")) {
    for (invalid in c("0", "-1")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        paste0(field, ".*positive")
      )
    }
  }
  for (field in c("panel_columns", "dpi")) {
    for (invalid in c("1.5", "2147483648.0")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        paste0(field, ".*positive integer")
      )
    }
  }
  for (invalid in c("-0.01", "1.01")) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace("significance_level", invalid))),
      "significance_level.*in"
    )
  }
  for (valid in c("0", "1")) {
    testthat::expect_equal(
      load_render_config(.write_render_config_test(.render_config_test_replace("significance_level", valid)))$significance_level,
      as.numeric(valid)
    )
  }
  for (invalid in c("null", "0.3", "{min: -0.3, max: 0.3}", "[]", "[-0.3]", "[-0.3, 0, 0.3]",
                    "['-0.3', 0.3]", "[false, true]", "[-.inf, 0.3]", "[-0.3, .nan]", "[1, -1]", "[1, 1]")) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace("y_limits", invalid))),
      "y_limits"
    )
  }
  testthat::expect_error(
    load_render_config(.write_render_config_test(.render_config_test_replace("dpi", "2147483648"))),
    "YAML could not be parsed.*integer range"
  )
})

testthat::test_that("render dimensions and break counts have realizable safety bounds", {
  for (field in c("width", "height")) {
    for (invalid in c("0.0001", "10000000", "1.0e+308")) {
      testthat::expect_error(
        load_render_config(.write_render_config_test(.render_config_test_replace(field, invalid))),
        paste0(field, ".*dpi.*pixels")
      )
    }
  }
  for (lines in list(
    c("y_limits: [0, 1]", "y_break_interval: 0.0001"),
    c("y_limits: [-1.0e+308, 1.0e+308]"),
    c("y_limits: [-1.0e+300, 1.0e+300]", "y_break_interval: 1.0e-300")
  )) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(c(.render_config_test_lines(), lines))),
      "at most 10,000 y-axis breaks"
    )
  }
  testthat::expect_no_error(load_render_config(.write_render_config_test(c(
    .render_config_test_lines(), "y_limits: [0, 9999]", "y_break_interval: 1"
  ))))
})

testthat::test_that("render paths enforce extensions, existence and distinct resolved files", {
  for (case in list(
    c("results_paths", "[one.txt]", "results_paths.*csv"),
    c("results_paths", "[missing.csv]", "input result CSV does not exist"),
    c("results_paths", "[one.csv, one.csv]", "duplicate value"),
    c("results_paths", "[one.csv, ./one.csv]", "distinct input CSVs"),
    c("output_path", "figure.pdf", "output_path.*png")
  )) {
    testthat::expect_error(
      load_render_config(.write_render_config_test(.render_config_test_replace(case[1], case[2]))),
      case[3]
    )
  }
  input_dir <- .write_render_config_test(.render_config_test_replace("results_paths", "[directory.csv]"))
  dir.create(file.path(dirname(input_dir), "directory.csv"))
  testthat::expect_error(load_render_config(input_dir), "input result path is a directory")

  output_dir <- .write_render_config_test(.render_config_test_replace("output_path", "figure.png"))
  dir.create(file.path(dirname(output_dir), "figure.png"))
  testthat::expect_error(load_render_config(output_dir), "output PNG path is a directory")

  alias <- .write_render_config_test(.render_config_test_replace("results_paths", "[one.csv, alias.csv]"))
  testthat::expect_true(file.symlink(file.path(dirname(alias), "one.csv"), file.path(dirname(alias), "alias.csv")))
  testthat::expect_error(load_render_config(alias), "distinct input CSVs")

  collision <- .write_render_config_test(.render_config_test_replace("output_path", "alias.png"))
  testthat::expect_true(file.symlink(file.path(dirname(collision), "one.csv"), file.path(dirname(collision), "alias.png")))
  testthat::expect_error(load_render_config(collision), "output_path.*distinct from every input CSV")
})
