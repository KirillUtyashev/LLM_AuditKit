# Loading Pipeline Datasets

Dataset loading turns a local file or a same-schema directory
into the normalized `pandas.DataFrame` used by the rest of LLM AuditKit. It preserves
caller columns, validates the fields needed by the next stage, and supplies stable
scenario IDs without using row numbers.

For the complete format and failure contract, see the
[dataset loading component documentation](../components/dataset_loading.md).

## Load a Local File

Define the minimum schema needed by the stage that will consume the DataFrame:

```python
from llm_auditkit.data import (
    DatasetLoader,
    DatasetSchema,
    LocalDatasetSource,
)

schema = DatasetSchema(
    required_columns=["Text", "Category", "Year"],
    nonempty_columns=["Text"],
    optional_columns={
        "City": "location-specific prompt context will be unavailable",
    },
)

dataset = DatasetLoader(schema).load(
    LocalDatasetSource("data/job_postings.csv")
)
```

CSV, TSV, record-oriented JSON, and JSON Lines are supported. The format is inferred
from the extension. For an extensionless single file, pass `file_format="csv"`,
`"tsv"`, `"json"`, or `"jsonl"` explicitly.

The loader converts scalar cells to pandas string dtype while preserving missing
values. Literal CSV values such as `NA` and identifiers such as `00007` remain literal
strings. Additional columns are preserved. CSV/TSV inputs containing NUL characters
are rejected. The CSV parser defaults to 131,072 characters per field; for longer
cells, set Python's `csv.field_size_limit()` before loading.

## Load a Directory

Pass a directory to concatenate all immediately contained supported files:

```python
dataset = DatasetLoader(schema).load(
    LocalDatasetSource("data/job_posting_parts")
)
```

Files are processed in deterministic filename order. Every file must have the same
column set, although column order may differ. Unsupported files and nested directories
are ignored. Include a stable replicate column when intentionally duplicated rows need
to remain separate scenarios.

Remote downloads are outside the current scope. Download a hosted dataset to a local
file before using the loader.

## Understand Validation and Warnings

Missing required columns or empty values in `nonempty_columns` stop loading. Missing
optional columns emit `MissingOptionalColumnWarning` values but return the DataFrame.
Applications can use Python's standard warnings controls to display, capture, or treat
these warnings as errors.

The schema is intentionally caller-configured. Dataset loading does not force every
pipeline to use a column named `Text`; a template-generation composition layer can map
its configured job-posting and context columns, while experiment execution can map its
job-posting and resume columns.

## Understand Scenario IDs

If the source already contains `scenario_id`, its unique nonempty values are preserved
as strings. Otherwise AuditKit appends an ID derived from the complete normalized row.
The derived value is unaffected by DataFrame index or column order.

Exact duplicate rows cannot receive distinct content-derived IDs and are rejected.
Add a stable source column such as `replicate_id`, or supply unique canonical scenario
IDs, when duplicate content is intentional.
