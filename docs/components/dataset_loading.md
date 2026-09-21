# Dataset Loading

[View the dataset loading diagram.](../architecture/dataset_loading.mmd)

## Overview

Dataset loading is the single path-or-URL-to-DataFrame boundary in the Python
pipeline. It reads a configured local or remote tabular source, normalizes it into a
common `pandas.DataFrame`, validates the caller's minimum schema, and establishes
stable `scenario_id` values before handing the DataFrame to downstream stages.

Template generation and experiment execution accept DataFrames and do not implement
their own source readers. A command-line or composition layer may construct a dataset
source and invoke `DatasetLoader`; downstream domain APIs remain path-independent.

## Public Model

The stage consists of:

- `DatasetSource`, a protocol whose `load()` method returns one raw DataFrame;
- `LocalDatasetSource`, for one local file or a local directory;
- `RemoteDatasetSource`, for a configured HTTP(S) resource;
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

An explicit format is useful when a single remote resource or local file has no
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

## Remote Sources

`RemoteConfig` contains:

- `backend`, initially the single value `http`;
- `url`, whose scheme must be `http` or `https`;
- optional `file_format`, otherwise inferred from the URL path;
- optional `credential_env`, naming an environment variable that contains a bearer
  token;
- positive `timeout_seconds`; and
- positive `max_bytes`, which bounds the response read into memory.

`RemoteDatasetSource` uses the standard-library HTTP client, follows its normal
redirect behavior, and parses the downloaded bytes with the same format readers as a
local file. When `credential_env` is configured, the source reads it at request time
and sends `Authorization: Bearer <value>`. Configuration stores only the environment
variable name. Missing credentials fail before the request, and credential values are
never included in errors.

Responses larger than `max_bytes`, unsupported URL schemes, download failures, and
unrecognized formats raise `DatasetSourceError`. Other remote backends can be added
behind the source protocol without changing `DatasetLoader` or downstream stages.

## Normalized DataFrame Contract

After a source returns, `DatasetLoader`:

1. requires a DataFrame with unique string column names;
2. rejects nested container values because downstream stages require scalar cells;
3. converts every nonmissing scalar cell to pandas' string dtype;
4. preserves native missing values as `pd.NA` and preserves explicit CSV/TSV empty
   strings as empty strings;
5. resets the DataFrame index, which is never durable identity;
6. preserves and validates a supplied `scenario_id`, or appends a derived one; and
7. runs `DatasetValidator` against the normalized result.

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
dataset-loading exception types. Reader and transport exceptions are wrapped with the
source operation and exception type while retaining the original exception as the
cause. Remote credentials and response contents are not copied into error messages.

Loading and validation perform no LLM calls, retries, or checkpoint writes. A failure
returns no partial DataFrame.
