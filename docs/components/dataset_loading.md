# Dataset Loading

[View the dataset loading diagram.](../architecture/dataset_loading.mmd)

## Overview

The dataset loading stage loads local or remote tabular data into a common `pandas.DataFrame` representation.

## Input Sources

The package supports two source types:

- `LocalDatasetSource`
- `RemoteDatasetSource`

### Local Sources

Users provide a path to either:

- a supported file; or
- a directory containing supported files.

For a single file, the format is inferred from the extension.

For a directory, all supported files are loaded and concatenated into one DataFrame.

### Remote Sources

Remote datasets are configured through `RemoteConfig`, which specifies:

- backend;
- URL or remote location;
- the environment variable or secret reference used for authentication.

## Output

All dataset sources return a `pandas.DataFrame`.

Downstream pipeline stages do not need to know where the dataset originated.

Before a row enters a resumable downstream inference stage, it must have a stable `scenario_id`. An identifier supplied by the source is preserved; otherwise, one is generated once and persisted with the dataset. Template generation and experiment execution use this identifier for request association and resume behavior; neither may use a DataFrame row index as durable identity.

## Core Validation

`DatasetValidator` checks the minimum schema required by the package.

Currently, the dataset must contain:

- `Text`

A missing required field prevents the dataset from entering the pipeline.

## Pipeline-Specific Validation

Later stages may check for additional optional fields.

For example, template generation may use:

- `Year`
- `Month`
- `Day`
- `Category`

Missing optional fields should produce a warning describing how the behavior of that stage will change.

## Design Principles

- Loading and validation are separate responsibilities.
- Source implementations normalize data into the same DataFrame format.
- Optional fields are checked only by pipeline stages that use them.
