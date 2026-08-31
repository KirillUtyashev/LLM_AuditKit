# Pure figure construction. Selection, compatibility checks, significance
# classification, and deterministic horizontal positions are prepared upstream.
.regression_plot_palette <- function(series_order) {
  # Lock the historical ggplot-style hue palette instead of consulting a
  # session-wide palette option. Every panel uses the same complete mapping.
  hues <- seq(15, 375, length.out = length(series_order) + 1L)
  stats::setNames(
    grDevices::hcl(h = hues[seq_along(series_order)], c = 100, l = 65),
    series_order
  )
}

.regression_plot_panel <- function(
  prepared,
  panel_value,
  panel_index,
  panel_columns,
  panel_rows,
  x_limits,
  y_breaks,
  palette
) {
  config <- prepared$config
  data <- prepared$data[
    prepared$data$.plot_panel == panel_value,
    ,
    drop = FALSE
  ]
  has_series <- !is.null(config$series_variable)
  mapping <- if (has_series) {
    ggplot2::aes(x = .plot_x, y = estimate, colour = .plot_series)
  } else {
    ggplot2::aes(x = .plot_x, y = estimate)
  }

  plot <- ggplot2::ggplot(data, mapping) +
    ggplot2::geom_hline(
      yintercept = 0,
      linetype = "dotted",
      colour = "red"
    )

  interval_mapping <- ggplot2::aes(
    ymin = conf_low,
    ymax = conf_high,
    alpha = .plot_alpha
  )
  point_mapping <- ggplot2::aes(alpha = .plot_alpha)
  if (has_series) {
    plot <- plot +
      ggplot2::geom_errorbar(
        interval_mapping,
        width = prepared$cap_width,
        linewidth = 0.5,
        show.legend = FALSE
      ) +
      ggplot2::geom_point(point_mapping, size = 3, show.legend = TRUE) +
      ggplot2::scale_colour_manual(
        values = palette,
        limits = prepared$series_order,
        breaks = prepared$series_order,
        drop = FALSE,
        name = tools::toTitleCase(gsub("_", " ", config$series_variable)),
        guide = ggplot2::guide_legend(
          override.aes = list(alpha = 1, size = 3)
        )
      )
  } else {
    plot <- plot +
      ggplot2::geom_errorbar(
        interval_mapping,
        width = prepared$cap_width,
        linewidth = 0.5,
        colour = "#1f77b4",
        show.legend = FALSE
      ) +
      ggplot2::geom_point(
        point_mapping,
        size = 3,
        colour = "#1f77b4",
        show.legend = FALSE
      )
  }

  panel_row <- (panel_index - 1L) %/% panel_columns + 1L
  plot <- plot +
    ggplot2::scale_alpha_identity(guide = "none") +
    ggplot2::scale_x_continuous(
      breaks = prepared$period_positions,
      labels = prepared$period_order
    ) +
    ggplot2::scale_y_continuous(breaks = y_breaks) +
    # Coordinate zoom preserves coefficients and saved interval bounds even
    # when they extend beyond the visible y range. X limits align all panels.
    ggplot2::coord_cartesian(xlim = x_limits, ylim = config$y_limits) +
    ggplot2::labs(
      title = unname(prepared$panel_labels[[panel_value]]),
      x = config$x_label,
      y = config$y_label
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(
      axis.text.x = ggplot2::element_text(angle = 0, hjust = 0.5),
      plot.title = ggplot2::element_text(face = "bold", hjust = 0.5),
      plot.margin = ggplot2::margin(
        t = if (panel_row > 1L) 20 else 5,
        r = 5,
        b = if (panel_row < panel_rows) 20 else 5,
        l = 5,
        unit = "pt"
      )
    )

  if ((panel_index - 1L) %% panel_columns != 0L) {
    plot <- plot + ggplot2::theme(axis.title.y = ggplot2::element_blank())
  }
  plot
}

build_regression_plot <- function(prepared) {
  if (!inherits(prepared, "regression_plot_data")) {
    stop("prepared must be validated regression_plot_data.", call. = FALSE)
  }

  config <- prepared$config
  panel_columns <- min(config$panel_columns, length(prepared$panel_order))
  panel_rows <- ceiling(length(prepared$panel_order) / panel_columns)
  # Include the caps and all globally configured periods in each panel's view,
  # including periods with no selected result in an individual panel.
  x_limits <- range(
    prepared$period_positions,
    prepared$data$.plot_x - prepared$cap_width / 2,
    prepared$data$.plot_x + prepared$cap_width / 2
  )
  y_breaks <- seq(
    config$y_limits[[1L]],
    config$y_limits[[2L]],
    by = config$y_break_interval
  )
  # seq() may leave a tiny residue at zero, causing automatic tick labels to
  # switch to scientific notation. Scale-relative tolerance also works on
  # genuinely tiny axes without rounding their meaningful ticks to zero.
  zero_tolerance <- 4 * .Machine$double.eps * max(abs(config$y_limits))
  y_breaks[abs(y_breaks) <= zero_tolerance] <- 0
  palette <- if (is.null(config$series_variable)) {
    character()
  } else {
    .regression_plot_palette(prepared$series_order)
  }

  plots <- lapply(seq_along(prepared$panel_order), function(index) {
    .regression_plot_panel(
      prepared = prepared,
      panel_value = prepared$panel_order[[index]],
      panel_index = index,
      panel_columns = panel_columns,
      panel_rows = panel_rows,
      x_limits = x_limits,
      y_breaks = y_breaks,
      palette = palette
    )
  })

  patchwork::wrap_plots(
    plots,
    ncol = panel_columns,
    byrow = TRUE,
    guides = "collect"
  ) & ggplot2::theme(
    legend.position = if (is.null(config$series_variable)) "none" else "bottom"
  )
}
