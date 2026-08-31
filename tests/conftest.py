"""Repository-wide pytest configuration."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the explicit safety gate for paid live-inference tests."""

    group = parser.getgroup("live inference")
    group.addoption(
        "--run-live-inference",
        action="store_true",
        default=False,
        help="run tests that make paid calls to external model providers",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip every live-inference test unless the safety flag is present."""

    if config.getoption("--run-live-inference"):
        return

    skip_live = pytest.mark.skip(
        reason="requires the explicit --run-live-inference option",
    )
    for item in items:
        if item.get_closest_marker("live_inference") is not None:
            item.add_marker(skip_live)
