"""Sample synthetic assignments, then populate the same templates without inference.

This is an editable research example, not a package sampling policy. Pools are
independent; correlated profiles and historical/demographic rules need an
explicit researcher-defined design instead.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile

import pandas as pd
import yaml

from llm_auditkit.data import DatasetLoader, DatasetSchema, LocalDatasetSource
from llm_auditkit.templates._sampling import sample_candidates
from llm_auditkit.templates.population import TemplatePopulationConfig, TemplatePopulator


def _write_csv(table: pd.DataFrame, path: Path) -> None:
    """Replace one complete CSV atomically; never expose a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            table.to_csv(stream, index=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(config_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load once, sample, populate in memory, then save both validated tables."""
    config_path = Path(config_path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    population = TemplatePopulationConfig(**config["population"])
    resolve = lambda value: (config_path.parent / value).resolve()
    source = resolve(config["dataset_path"])
    candidates_path = resolve(config["output"]["candidates_path"])
    populated_path = resolve(config["output"]["populated_path"])
    if candidates_path == populated_path or {source, config_path} & {candidates_path, populated_path}:
        raise ValueError("Outputs must be distinct and cannot overwrite the input or configuration")
    templates = DatasetLoader(DatasetSchema(required_columns=[
        population.job_posting_column, *population.template_columns.values(),
    ])).load(LocalDatasetSource(source))
    replacements = sample_candidates(templates, population, **config["sampling"])
    populated = TemplatePopulator().populate(templates, replacements, population)
    # Both tables are valid before either is saved. Each file replacement is
    # atomic, but these two files are not a transactional pair: rerun if interrupted.
    _write_csv(replacements, candidates_path)
    _write_csv(populated, populated_path)
    return replacements, populated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    candidates, populated = run(args.config)
    print(f"Saved {len(candidates)} candidate assignments and {len(populated)} populated scenarios.")


if __name__ == "__main__":
    main()
