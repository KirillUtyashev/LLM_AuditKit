# Render saved regression results

From the repository root, after restoring the R environment:

```bash
Rscript -e 'renv::restore(prompt = FALSE)'
Rscript scripts/render_regression_plot.R --config examples/regression/render_synthetic.yaml
```

The command creates `outputs/regression/synthetic_paper_style.png`: four panels
at 3600 × 2400 pixels, with saved 95% confidence intervals, a dotted red zero
line, and lower opacity where the saved p-value is at least 0.05. No raw data,
private reference checkout, or regression fitting is needed. The output is
ignored by Git. A successful rerun replaces that PNG atomically.

## What the example represents

The [configuration](render_synthetic.yaml) reads
[a public synthetic result fixture](../../tests/r/fixtures/regression/render_results_synthetic.csv).
It contains 24 invented coefficient summaries: four fictional model panels,
six periods, and three saved interval levels (72 rows). These are plotting
examples, not results from actual job posts or estimates of discrimination.

The fixture's estimator marker is deliberately `synthetic_summary`, with
`synthetic_t394_v1` identifying illustrative t-based intervals and p-values.
Estimates and standard errors were chosen to exercise the display; count and
provenance fields are synthetic as well. Nothing was copied from private
sample datasets or empirical paper results. Automated tests separately check
that actual `fixest::feols` output from the public regression-ready fixture
feeds the same renderer without any schema adaptation.

The example explicitly maps Model A to `pick_top` and Models B–D to
`pick_threshold`, demonstrating the paper's mixed-outcome panel convention
without suggesting these fictional models reproduce its findings.

The same CSV can be plotted interactively from a clean R session:

```r
source("R/regression/load.R")

config <- regression_plot_config(
  term = "black",
  period_variable = "period",
  panel_variable = "model_config_id",
  outcome_by_panel = c(
    model_a = "pick_top",
    model_b = "pick_threshold",
    model_c = "pick_threshold",
    model_d = "pick_threshold"
  ),
  panel_order = c("model_a", "model_b", "model_c", "model_d")
)
figure <- plot_regression_results(
  "tests/r/fixtures/regression/render_results_synthetic.csv",
  config
)
figure
```

`plot_regression_results()` also accepts the object returned by
`estimate_regressions()` or a list of compatible result tables.

## Use your own saved results

Copy the YAML and change `results_paths`, `output_path`, `term`, the outcome
selection, and the period/series/panel roles. Paths are relative to the YAML
file's directory. Keep the original result schema and metadata when saving a
slice.

- Use `confidence_level: 0.90`, `0.95`, or `0.99` to select stored bounds.
  The renderer never calculates new confidence intervals or fits models.
- `term` is the saved independent-variable coefficient shown on the y-axis.
  It is separate from the dependent-variable selection.
- Use `outcome_variable: pick_top` for one common dependent variable, or omit
  it and map every observed panel with `outcome_by_panel`. Exactly one mode is
  required; there is no implicit outcome choice.
- Set `series_variable` to a saved grouping column (for example `city`) for
  colored series and a shared bottom legend. Include that column in the
  estimation grouping first; rendering cannot recover a dimension that was
  pooled away.
- Set `panel_variable: null` for one panel. For separately estimated
  specifications, use a field such as `model_id` as the panel variable and
  label each panel clearly.
- Order lists must include every selected value exactly once. For a subset,
  save an inspected CSV slice first. Unmapped grouping columns must be
  constant within each selected panel.
- Change `panel_labels`, axis labels, y limits, dimensions, or DPI as needed.
  Y limits zoom the display without deleting out-of-range coefficients.

Results used in one figure must share dataset, estimation-group, inference, and
preparation metadata. Formula and covariance specifications may differ across
explicit panels but must remain constant within each panel. A different
`model_id` does not waive those checks. The default figure is paper-style, not
a pixel-identical copy of the historical output; it uses modern saved intervals
and the local PNG backend.

See the [complete rendering contract](../../docs/components/regression_analysis.md#3-paper-style-rendering)
for every option. The same result CSV remains available for other plotting
tools and designs; this renderer is optional.
