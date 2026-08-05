# Regression Analysis

[View the regression analysis diagram.](architecture/regression_analysis.mmd)

## Overview

The regression analysis stage processes experiment outputs, estimates configured regression models, and produces reusable result artifacts.

This stage is implemented in R.

## Input

The analysis reads completed experiment result CSV files from the configured data path.

Data may be loaded across multiple years or experiment partitions before being combined and processed.

## Configuration

`RegressionConfig` is loaded from a YAML file and includes:

- data path;
- years to include;
- outcome variable;
- explanatory variable;
- control variables;
- fixed effects;
- clustering variables;
- output directory.

## Invocation

The regression pipeline is invoked through an R command-line script. The YAML configuration path is passed with `--config`:

```bash
Rscript scripts/run_regression.R --config path/to/regression.yaml
```

The script reads command-line arguments with `commandArgs(trailingOnly = TRUE)` or an R argument-parsing package and loads the configuration using the R `yaml` package.

## Processing

The R pipeline performs the following steps:

1. Load experiment results.
2. Combine data across years or other partitions.
3. Clean and reshape the data.
4. Construct derived analysis variables.
5. Estimate the configured regression model.
6. Extract regression statistics.
7. Generate plots from the regression estimates.

## Regression Outputs

Raw regression results are saved as CSV files.

These should include, where applicable:

- coefficient estimates;
- standard errors;
- confidence intervals;
- p-values;
- sample sizes;
- model specification metadata.

## Plot Outputs

Regression plots are saved as PNG files.

All artifacts are written to the configured output directory.

Example:

```text
outputs/
├── regression_results.csv
├── regression_plot.png
└── additional_plots/
```

## Design Principles

- Regression estimation and plotting remain in R.
- Model specification is controlled through configuration rather than hard-coded paths or variables.
- Raw numerical results are always saved separately from plots.
- Plots should be reproducible directly from the saved regression results.
