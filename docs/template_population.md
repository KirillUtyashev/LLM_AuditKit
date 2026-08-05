# Template Population

[View the template population diagram.](architecture/template_population.mmd)

## Overview

The template population stage deterministically replaces placeholders in generated resume templates. No LLM calls are made during this stage.

## Input

- Output of the template generation stage.
- `TemplatePopulationConfig`.

## Output

A populated `pandas.DataFrame` containing the same configurable number `N` of fully instantiated resume templates per scenario, ready for experiment execution.

## Configuration

Population behavior is controlled through `TemplatePopulationConfig`, including:

- Placeholder values.
- Population strategy configuration.

## Population Strategy

Population algorithms are implemented through the `PopulationStrategy` interface.

The package provides `DefaultPopulationStrategy`, while users may implement custom strategies by extending the interface.

## Processing

For each template:

1. Identify placeholders.
2. Determine replacement values using the configured population strategy.
3. Replace placeholders deterministically.
4. Store the populated template in the output dataset.

## Notes

- No LLM inference is performed.
- The original dataset structure is preserved.
- The stage is deterministic given the same configuration.
