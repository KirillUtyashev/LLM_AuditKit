"""Internal opt-in pool sampling shared by the repository runner and example.

This is not part of TemplatePopulator's API. Pools and their substantive meaning
are researcher-supplied; this helper never infers demographic or quality labels.
"""

from __future__ import annotations

import hashlib
import json
import random
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from .population import TemplatePopulationConfig


STRUCTURAL_COLUMNS = {"scenario_id", "template_id", "candidate_id", "candidate_order"}


def validate_sampling(population, *, pools, unique_columns, seed, assignment_namespace) -> None:
    """Validate the entire sampling design without loading data or drawing values."""
    if type(seed) is not int or not isinstance(assignment_namespace, str) or not assignment_namespace.strip():
        raise ValueError("Supply an integer seed and a nonblank assignment_namespace")
    if not population.template_columns:
        raise ValueError("Configure at least one template")
    if not isinstance(pools, dict) or any(
        not isinstance(column, str) or not column.strip() or column in STRUCTURAL_COLUMNS
        or not isinstance(values, list) or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
        for column, values in pools.items()
    ):
        raise ValueError("Pools must map payload columns to nonempty lists of distinct, nonblank strings")
    if not set(population.placeholder_columns.values()) <= set(pools):
        raise ValueError("Every mapped placeholder column needs a pool")
    if (
        not isinstance(unique_columns, list)
        or any(not isinstance(column, str) for column in unique_columns)
        or len(set(unique_columns)) != len(unique_columns)
        or not set(unique_columns) <= set(pools)
    ):
        raise ValueError("unique_columns must name distinct configured pools")
    if any(len(pools[column]) < len(population.template_columns) for column in unique_columns):
        raise ValueError("Unique pools need at least one value per configured template")


def sample_candidates(
    templates: pd.DataFrame,
    population: TemplatePopulationConfig,
    *,
    pools: dict[str, list[str]],
    unique_columns: list[str],
    seed: int,
    assignment_namespace: str,
) -> pd.DataFrame:
    """Draw exact assignments reproducibly, independently of scenario row order.

    Unique pools reset per scenario; other pools permit repeated values. Slots
    are shuffled. The design/identity algorithm matches the standalone example.
    """
    validate_sampling(population, pools=pools, unique_columns=unique_columns,
                      seed=seed, assignment_namespace=assignment_namespace)
    if (
        "scenario_id" not in templates
        or templates.empty
        or not templates.scenario_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all()
        or templates.scenario_id.duplicated().any()
    ):
        raise ValueError("Templates must contain unique, nonblank scenario_id strings")
    template_ids = sorted(population.template_columns)
    design = {"version": 1, "namespace": assignment_namespace, "seed": seed,
              "templates": dict(population.template_columns),
              "placeholders": dict(population.placeholder_columns),
              "pools": pools, "unique_columns": sorted(unique_columns)}
    rows = []
    for scenario_id in sorted(templates.scenario_id):
        identity = json.dumps([design, scenario_id], sort_keys=True, ensure_ascii=False)
        rng = random.Random(int.from_bytes(hashlib.sha256(identity.encode()).digest(), "big"))
        draws = {
            column: rng.sample(pools[column], len(template_ids)) if column in unique_columns
            else rng.choices(pools[column], k=len(template_ids))
            for column in sorted(pools)
        }
        orders = rng.sample(range(1, len(template_ids) + 1), len(template_ids))
        for index, template_id in enumerate(template_ids):
            payload = {column: values[index] for column, values in draws.items()}
            candidate_key = json.dumps([identity, template_id, payload], sort_keys=True)
            rows.append({"scenario_id": scenario_id, "template_id": template_id,
                         "candidate_id": str(uuid5(NAMESPACE_URL, candidate_key)),
                         "candidate_order": orders[index], **payload})
    return pd.DataFrame(rows)
