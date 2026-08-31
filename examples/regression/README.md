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

## Use your own saved results

Copy the YAML and change `results_paths`, `output_path`, `term`, and the period
and panel columns. Paths are relative to the YAML file's directory. Keep the
original result schema and preparation/model metadata when saving a slice.

- Use `confidence_level: 0.90`, `0.95`, or `0.99` to select stored bounds.
  The renderer never calculates new confidence intervals or fits models.
- Use `outcome_by_panel: {}` for one common outcome, or map every observed
  panel to its intended outcome. There is no implicit outcome choice.
- Set `series_variable` to a saved grouping column (for example `city`) for
  colored series and a shared bottom legend. Include that column in the
  estimation grouping first; rendering cannot recover a dimension that was
  pooled away.
- Order lists must include every selected value exactly once. For a subset,
  save an inspected CSV slice first. Unmapped grouping columns must be
  constant in the selected results.
- Change `panel_labels`, axis labels, y limits, dimensions, or DPI as needed.
  Y limits zoom the display without deleting out-of-range coefficients.

Results used in one figure must have compatible dataset, specification,
inference, and preparation metadata. A different `model_id` does not waive
those checks. The default figure is paper-style, not a pixel-identical copy
of the historical output; it uses modern saved intervals and the local PNG
backend.

See the [complete rendering contract](../../docs/components/regression_analysis.md#3-paper-style-rendering)
for every option. The same result CSV remains available for other plotting
tools and designs; this renderer is optional.
