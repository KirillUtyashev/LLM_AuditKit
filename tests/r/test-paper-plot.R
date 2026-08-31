.paper_plot_fixture <- function(series = FALSE) {
  # This fixture represents the in-memory contract after result validation and
  # selection. It needs neither a result CSV nor a fitted regression object.
  panels <- c("model-c", "model-a", "model-d", "model-b")
  periods <- c("1970", "1980", "1990")
  series_order <- if (series) c("Toronto", "New_York", "Seattle") else character()
  data <- expand.grid(
    .plot_series = if (series) series_order else "",
    .plot_period = periods,
    .plot_panel = panels,
    stringsAsFactors = FALSE
  )
  period_index <- match(data$.plot_period, periods)
  data$dataset_id <- "synthetic_plot_fixture"
  data$model_id <- "black_baseline"
  data$outcome_variable <- "pick_top"
  data$term <- "black"
  data$confidence_level <- 0.95
  data$estimate <- c(-0.35, 0.06, 0.34)[period_index]
  # Deliberately not normal-approximation intervals from this SE: plotting must
  # consume these saved bounds, never calculate replacements.
  data$std_error <- 7.77
  data$conf_low <- data$estimate - c(0.15, 0.07, 0.09)[period_index]
  data$conf_high <- data$estimate + c(0.11, 0.12, 0.06)[period_index]
  data$p_value <- c(0.01, 0.05, 0.2)[period_index]
  data$.plot_alpha <- ifelse(data$p_value < 0.05, 1, 0.3)
  data$.plot_x <- as.numeric(data$.plot_period)
  if (series) {
    # All panels receive the same global slots, including sparse combinations.
    offsets <- c(-0.6, 0, 0.6)
    data$.plot_x <- data$.plot_x + offsets[
      match(data$.plot_series, series_order)
    ]
  }
  config <- structure(
    list(
      series_variable = if (series) "city" else NULL,
      panel_columns = 2L,
      x_label = "Period",
      y_label = "Black coefficient estimate",
      y_limits = c(-0.3, 0.3),
      y_break_interval = 0.1,
      significance_level = 0.05
    ),
    class = "render_config"
  )
  structure(
    list(
      data = data,
      config = config,
      period_order = periods,
      panel_order = panels,
      series_order = series_order,
      period_positions = as.numeric(periods),
      panel_labels = stats::setNames(
        paste0("Panel ", LETTERS[seq_along(panels)], ": ", panels),
        panels
      ),
      cap_width = 0.8
    ),
    class = "regression_plot_data"
  )
}

.paper_plot_grob <- function(figure) {
  # Grob measurement can open R's default device. Explicitly use an in-memory
  # device to avoid leaving Rplots.pdf in the repository during tests.
  grDevices::pdf(NULL)
  device <- grDevices::dev.cur()
  on.exit(grDevices::dev.off(device), add = TRUE)
  patchwork::patchworkGrob(figure)
}

.paper_plot_collect_grobs <- function(grob, class_name) {
  matches <- if (inherits(grob, class_name)) list(grob) else list()
  children <- c(grob$grobs, as.list(grob$children))
  for (child in children) {
    matches <- c(matches, .paper_plot_collect_grobs(child, class_name))
  }
  matches
}

testthat::test_that("paper plots preserve saved numerical data and alpha", {
  prepared <- .paper_plot_fixture()
  original <- prepared
  figure <- build_regression_plot(prepared)

  testthat::expect_s3_class(figure, "patchwork")
  testthat::expect_identical(prepared, original)
  for (index in seq_along(prepared$panel_order)) {
    panel <- figure[[index]]
    expected <- prepared$data[
      prepared$data$.plot_panel == prepared$panel_order[[index]],
      ,
      drop = FALSE
    ]
    built <- ggplot2::ggplot_build(panel)
    intervals <- built$data[[2L]]
    points <- built$data[[3L]]

    testthat::expect_identical(panel$data, expected)
    testthat::expect_identical(panel$data$p_value, expected$p_value)
    testthat::expect_identical(points$x, expected$.plot_x)
    testthat::expect_identical(points$y, expected$estimate)
    testthat::expect_identical(intervals$ymin, expected$conf_low)
    testthat::expect_identical(intervals$ymax, expected$conf_high)
    testthat::expect_identical(points$alpha, expected$.plot_alpha)
    testthat::expect_identical(intervals$alpha, expected$.plot_alpha)
    testthat::expect_identical(points$alpha[expected$p_value == 0.05], 0.3)
    testthat::expect_true(all(points$size == 3))
    testthat::expect_true(all(intervals$linewidth == 0.5))
    testthat::expect_equal(
      intervals$xmax - intervals$xmin,
      rep(prepared$cap_width, nrow(expected))
    )
  }
})

testthat::test_that("coordinate zoom retains estimates and intervals outside view", {
  prepared <- .paper_plot_fixture()
  figure <- build_regression_plot(prepared)
  panel <- figure[[1L]]
  built <- ggplot2::ggplot_build(panel)

  testthat::expect_identical(panel$coordinates$limits$y, prepared$config$y_limits)
  testthat::expect_null(panel$scales$get_scales("y")$limits)
  testthat::expect_identical(nrow(built$data[[2L]]), 3L)
  testthat::expect_identical(nrow(built$data[[3L]]), 3L)
  testthat::expect_true(all(is.finite(built$data[[2L]]$ymin)))
  testthat::expect_true(all(is.finite(built$data[[2L]]$ymax)))
  testthat::expect_true(any(built$data[[3L]]$y < prepared$config$y_limits[[1L]]))
  testthat::expect_true(any(built$data[[3L]]$y > prepared$config$y_limits[[2L]]))
  testthat::expect_warning(.paper_plot_grob(figure), NA)
})

testthat::test_that("fixed-blue mode has the paper zero line and no legend", {
  prepared <- .paper_plot_fixture()
  figure <- build_regression_plot(prepared)
  for (index in seq_along(prepared$panel_order)) {
    panel <- figure[[index]]
    built <- ggplot2::ggplot_build(panel)
    testthat::expect_true(all(built$data[[1L]]$yintercept == 0))
    testthat::expect_true(all(built$data[[1L]]$colour == "red"))
    testthat::expect_true(all(built$data[[1L]]$linetype == "dotted"))
    testthat::expect_true(all(built$data[[2L]]$colour == "#1f77b4"))
    testthat::expect_true(all(built$data[[3L]]$colour == "#1f77b4"))
    testthat::expect_identical(panel$theme$legend.position, "none")
    testthat::expect_null(panel$scales$get_scales("colour"))
  }
  grob <- .paper_plot_grob(figure)
  testthat::expect_false(any(grob$layout$name == "guide-box"))
})

testthat::test_that("sparse series retain global color mapping and supplied slots", {
  prepared <- .paper_plot_fixture(series = TRUE)
  data <- prepared$data
  prepared$data <- data[
    !(data$.plot_panel == "model-c" & data$.plot_series == "Toronto") &
      !(data$.plot_panel == "model-a" & data$.plot_period == "1980" &
        data$.plot_series == "New_York"),
    ,
    drop = FALSE
  ]
  figure <- build_regression_plot(prepared)
  expected_palette <- c("#F8766D", "#00BA38", "#619CFF")
  shared_x_limits <- figure[[1L]]$coordinates$limits$x

  for (index in seq_along(prepared$panel_order)) {
    panel <- figure[[index]]
    expected <- prepared$data[
      prepared$data$.plot_panel == prepared$panel_order[[index]],
      ,
      drop = FALSE
    ]
    built <- ggplot2::ggplot_build(panel)
    scale <- panel$scales$get_scales("colour")
    expected_colors <- expected_palette[
      match(expected$.plot_series, prepared$series_order)
    ]
    testthat::expect_identical(scale$limits, prepared$series_order)
    testthat::expect_identical(scale$breaks, prepared$series_order)
    testthat::expect_false(scale$drop)
    testthat::expect_identical(built$data[[3L]]$x, expected$.plot_x)
    testthat::expect_identical(built$data[[2L]]$x, expected$.plot_x)
    testthat::expect_identical(built$data[[3L]]$colour, expected_colors)
    testthat::expect_identical(built$data[[2L]]$colour, expected_colors)
    testthat::expect_identical(panel$coordinates$limits$x, shared_x_limits)
  }
})

testthat::test_that("nonsignificant series have one complete opaque bottom legend", {
  prepared <- .paper_plot_fixture(series = TRUE)
  prepared$data$p_value <- 0.8
  prepared$data$.plot_alpha <- 0.3
  prepared$data <- prepared$data[
    !(prepared$data$.plot_panel == "model-c" &
      prepared$data$.plot_series == "Toronto"),
    ,
    drop = FALSE
  ]
  figure <- build_regression_plot(prepared)

  for (index in seq_along(prepared$panel_order)) {
    panel <- figure[[index]]
    points <- ggplot2::ggplot_build(panel)$data[[3L]]
    testthat::expect_true(all(points$alpha == 0.3))
    testthat::expect_identical(panel$theme$legend.position, "bottom")
    testthat::expect_identical(
      panel$scales$get_scales("colour")$guide$params$override.aes$alpha,
      1
    )
  }
  testthat::expect_warning(grob <- .paper_plot_grob(figure), NA)
  legend_index <- which(grob$layout$name == "guide-box")
  testthat::expect_length(legend_index, 1L)
  panel_bottoms <- grob$layout$b[grepl("^panel-[0-9]+$", grob$layout$name)]
  testthat::expect_gt(length(panel_bottoms), 0L)
  testthat::expect_gt(grob$layout$t[[legend_index]], max(panel_bottoms))
  legend <- grob$grobs[[legend_index]]
  labels <- unlist(lapply(
    .paper_plot_collect_grobs(legend, "text"),
    function(item) as.character(item$label)
  ))
  testthat::expect_identical(
    labels[labels %in% prepared$series_order],
    prepared$series_order
  )
  testthat::expect_true("City" %in% labels)
  legend_points <- .paper_plot_collect_grobs(legend, "points")
  testthat::expect_length(legend_points, length(prepared$series_order))
  colors <- unlist(lapply(legend_points, function(item) item$gp$col))
  testthat::expect_true(all(grDevices::col2rgb(colors, alpha = TRUE)[4L, ] == 255))
})

testthat::test_that("two-column paper layout preserves titles axes and row margins", {
  prepared <- .paper_plot_fixture()
  figure <- build_regression_plot(prepared)

  testthat::expect_identical(figure$patches$layout$ncol, 2L)
  testthat::expect_true(figure$patches$layout$byrow)
  for (index in seq_along(prepared$panel_order)) {
    panel <- figure[[index]]
    testthat::expect_identical(
      panel$labels$title,
      unname(prepared$panel_labels[[prepared$panel_order[[index]]]])
    )
    testthat::expect_identical(panel$theme$plot.title$face, "bold")
    testthat::expect_identical(panel$theme$plot.title$hjust, 0.5)
    testthat::expect_identical(panel$theme$axis.text.x$angle, 0)
    testthat::expect_identical(panel$labels$x, prepared$config$x_label)
    testthat::expect_identical(panel$labels$y, prepared$config$y_label)
    testthat::expect_identical(
      panel$scales$get_scales("x")$breaks,
      prepared$period_positions
    )
    testthat::expect_identical(
      panel$scales$get_scales("x")$labels,
      prepared$period_order
    )
    testthat::expect_equal(
      panel$scales$get_scales("y")$breaks,
      seq(-0.3, 0.3, by = 0.1)
    )
    testthat::expect_identical(
      inherits(panel$theme$axis.title.y, "element_blank"),
      index %% 2L == 0L
    )
    testthat::expect_identical(
      as.numeric(panel$theme$plot.margin),
      if (index <= 2L) c(5, 5, 20, 5) else c(20, 5, 5, 5)
    )
  }
})

testthat::test_that("paper y-axis labels use an exact zero and clean decimals", {
  figure <- build_regression_plot(.paper_plot_fixture())
  panel <- figure[[1L]]
  breaks <- panel$scales$get_scales("y")$breaks
  built <- ggplot2::ggplot_build(panel)

  testthat::expect_identical(breaks[[4L]], 0)
  testthat::expect_identical(
    built$layout$panel_params[[1L]]$y$get_labels(),
    c("-0.3", "-0.2", "-0.1", "0.0", "0.1", "0.2", "0.3")
  )
})

testthat::test_that("zero normalization preserves meaningful tiny-axis ticks", {
  prepared <- .paper_plot_fixture()
  scale <- 1e-20
  prepared$config$y_limits <- c(-0.3, 0.3) * scale
  prepared$config$y_break_interval <- 0.1 * scale
  for (field in c("estimate", "conf_low", "conf_high")) {
    prepared$data[[field]] <- prepared$data[[field]] * scale
  }
  figure <- build_regression_plot(prepared)
  panel <- figure[[1L]]
  breaks <- panel$scales$get_scales("y")$breaks
  labels <- ggplot2::ggplot_build(panel)$layout$panel_params[[1L]]$y$get_labels()

  testthat::expect_identical(breaks[[4L]], 0)
  testthat::expect_identical(sum(breaks == 0), 1L)
  testthat::expect_equal(breaks / scale, c(-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3))
  testthat::expect_length(unique(labels), 7L)

  prepared$config$y_limits <- c(1, 5) * scale
  prepared$config$y_break_interval <- scale
  figure <- build_regression_plot(prepared)
  positive_breaks <- figure[[1L]]$scales$get_scales("y")$breaks
  testthat::expect_true(all(positive_breaks > 0))
  testthat::expect_equal(positive_breaks / scale, 1:5)
})

testthat::test_that("custom display labels never merge raw panel identities", {
  prepared <- .paper_plot_fixture()
  prepared$panel_labels[] <- "Same displayed title"
  prepared$config$x_label <- "Experiment phase"
  prepared$config$y_label <- "Selected coefficient"
  prepared$period_positions <- c(1, 2, 3)
  old_period_order <- prepared$period_order
  prepared$period_order <- c("Before", "During", "After")
  positions <- match(prepared$data$.plot_period, old_period_order)
  prepared$data$.plot_period <- prepared$period_order[positions]
  prepared$data$.plot_x <- prepared$period_positions[positions]
  figure <- build_regression_plot(prepared)

  for (index in seq_along(prepared$panel_order)) {
    panel <- figure[[index]]
    testthat::expect_identical(panel$labels$title, "Same displayed title")
    testthat::expect_identical(
      unique(panel$data$.plot_panel),
      prepared$panel_order[[index]]
    )
    testthat::expect_identical(panel$labels$x, "Experiment phase")
    testthat::expect_identical(panel$labels$y, "Selected coefficient")
    testthat::expect_identical(
      panel$scales$get_scales("x")$labels,
      c("Before", "During", "After")
    )
    testthat::expect_identical(
      ggplot2::ggplot_build(panel)$data[[3L]]$x,
      c(1, 2, 3)
    )
  }
})

testthat::test_that("panel columns generalize without hiding left-column y titles", {
  prepared <- .paper_plot_fixture()
  prepared$config$panel_columns <- 3L
  figure <- build_regression_plot(prepared)
  testthat::expect_identical(figure$patches$layout$ncol, 3L)
  for (index in seq_along(prepared$panel_order)) {
    testthat::expect_identical(
      inherits(figure[[index]]$theme$axis.title.y, "element_blank"),
      index %in% c(2L, 3L)
    )
  }

  prepared$panel_order <- prepared$panel_order[[1L]]
  prepared$data <- prepared$data[
    prepared$data$.plot_panel == prepared$panel_order,
    ,
    drop = FALSE
  ]
  figure <- build_regression_plot(prepared)
  testthat::expect_identical(figure$patches$layout$ncol, 1L)
  testthat::expect_identical(as.numeric(figure[[1L]]$theme$plot.margin), rep(5, 4L))
  testthat::expect_false(inherits(figure[[1L]]$theme$axis.title.y, "element_blank"))
})

testthat::test_that("plot building rejects an unprepared object", {
  testthat::expect_error(
    build_regression_plot(list()),
    "prepared must be validated regression_plot_data",
    fixed = TRUE
  )
})
