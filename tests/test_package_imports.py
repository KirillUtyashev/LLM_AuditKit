"""Smoke tests for the installable package scaffold."""

from __future__ import annotations

import importlib

import pytest


PACKAGE_MODULES = (
    "llm_auditkit",
    "llm_auditkit.config",
    "llm_auditkit.data",
    "llm_auditkit.inference",
    "llm_auditkit.results",
    "llm_auditkit.scenarios",
    "llm_auditkit.templates",
)


@pytest.mark.parametrize("module_name", PACKAGE_MODULES)
def test_package_modules_are_importable(module_name: str) -> None:
    """Every namespace in the scaffold is included in the installed package."""
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name
