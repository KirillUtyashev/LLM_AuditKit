# Dataset Loading

[View the dataset loading diagram.](../architecture/dataset_loading.mmd)

## Overview

Dataset loading is the single path-to-DataFrame boundary in the Python
pipeline. It reads a configured local tabular source, normalizes it into a
common `pandas.DataFrame`, validates the caller's minimum schema, and establishes
stable `scenario_id` values before handing the DataFrame to downstream stages.

Template generation and experiment execution accept DataFrames and do not implement
their own source readers. A command-line or composition layer may construct a dataset
source and invoke `DatasetLoader`; downstream domain APIs remain path-independent.

## Public Model

The stage consists of:

- `DatasetSource`, a protocol whose `load()` method returns one raw DataFrame;
- `LocalDatasetSource`, for one local file or a local directory;
- `DatasetSchema`, which defines required, nonempty, and optional fields;
- `DatasetValidator`, which applies that schema to a normalized DataFrame; and
- `DatasetLoader`, which coordinates source loading, normalization, stable identity,
  and validation.

The standard entry point is:

```python
dataset = DatasetLoader(schema).load(source)
```

Custom sources may implement `DatasetSource`. `DatasetLoader` still performs the same
normalization, identity, and validation steps for their returned DataFrames.

## Validation Schema

`DatasetSchema` contains:

- `required_columns`: ordered source columns that must exist;
- `nonempty_columns`: required columns whose value in every row must be a nonempty
  string; and
- `optional_columns`: a mapping from an optional column name to a concise explanation
  of how its absence changes downstream behavior.

`required_columns` is configurable rather than fixed to a repository-wide column such
as `Text`. For example, one source may call the job-posting column `Text`, while
another may use `job_posting`. A composition layer can construct the loading schema
from the domain-stage schema it intends to call.

Schema column names must be unique nonempty strings. Nonempty columns must also be
required, required and optional columns cannot overlap, and `scenario_id` is reserved
for the loader's identity contract.

Missing required columns and empty values in configured nonempty columns raise
`DatasetValidationError`. Each missing optional column emits one
`MissingOptionalColumnWarning` containing both its name and configured impact. Optional
warnings do not stop loading. Additional source columns are preserved.

## Local Sources

`LocalDatasetSource` accepts a file or directory path and an optional explicit
`file_format`. When no format is supplied, the source infers it from the lowercase
file extension.

The supported formats are:

| Format | Extensions | Input shape |
| --- | --- | --- |
| CSV | `.csv` | UTF-8 header and records |
| TSV | `.tsv` | UTF-8 tab-separated header and records |
| JSON | `.json` | an array of record objects |
| JSON Lines | `.jsonl`, `.ndjson` | one record object per nonempty line |

An explicit format is useful when a local file has no
meaningful extension. Compressed files, spreadsheets, and Parquet are not supported by
the initial implementation because they require additional format and dependency
contracts.

For a directory, the source loads only immediate files with supported extensions,
ordered deterministically by filename. Unsupported entries and subdirectories are
ignored. At least one supported file must exist. Every loaded file must contain the
same column set; files whose columns are merely ordered differently are reordered to
the first file before concatenation. Source row order is preserved within each file.
An explicit `file_format` is not accepted for directory sources because each file is
inferred independently.

CSV and TSV reject NUL characters rather than silently truncating cells. Their initial
per-field limit follows Python's `csv.field_size_limit()` (131,072 characters by
default); oversized fields raise `DatasetSourceError`. Applications that need longer
fields may set that standard-library limit before loading. JSON Lines records are
separated by LF (including CRLF files); Unicode separators inside strings are preserved.

Remote downloads are outside the current scope. Download hosted datasets to a local
file before loading them.

## Normalized DataFrame Contract

After a source returns, `DatasetLoader`:

1. requires a DataFrame with unique string column names;
2. rejects nested container values because downstream stages require scalar cells;
3. converts every nonmissing scalar cell to pandas' string dtype;
4. preserves native missing values as `pd.NA` and preserves explicit CSV/TSV empty
   strings as empty strings;
5. resets the DataFrame index, which is never durable identity;
6. runs `DatasetValidator` against the normalized result; and
7. preserves and validates a supplied `scenario_id`, or appends a derived one.

The returned DataFrame contains the source columns in their source order plus a
canonical `scenario_id` when one was not already present. Loading never mutates a
DataFrame returned by a custom source.

## Stable Scenario Identity

If the source contains `scenario_id`, normalized values must be unique nonempty
strings and are preserved. Otherwise the loader hashes the complete normalized source
row as sorted column/value pairs and prefixes the digest with `scenario:`. Column order
and the original DataFrame index therefore do not affect identity.

Exact duplicate source rows derive the same ID and are rejected. Callers that intend
to retain repeated scenarios must include an ordinary stable replicate column or
provide unique canonical IDs. Source file position, directory enumeration position,
and DataFrame row number are never used as durable identity.

The identity functions live in the data package and are shared with downstream stages
so direct DataFrame use and loader-produced DataFrames follow the same algorithm.

## Failure Contract

Configuration, source, normalization, identity, and schema failures use distinct
dataset-loading exception types. Reader exceptions are wrapped with the source operation and exception type while
retaining the original exception as the cause.

Loading and validation perform no LLM calls, retries, or checkpoint writes. A failure
returns no partial DataFrame.
