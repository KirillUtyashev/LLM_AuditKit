"""Repository-wide pytest configuration."""

from __future__ import annotations

import pytest


@pytest.fixture
def offline_edsl(tmp_path, monkeypatch):
    """Isolate native EDSL test jobs from user storage and network access."""
    import socket
    from edsl.config import CONFIG
    from edsl.object_store.store import ObjectStore

    root = tmp_path / "objects"
    if hasattr(ObjectStore, "default_root"):  # EDSL 1.0.9
        monkeypatch.setattr(ObjectStore, "default_root", staticmethod(lambda: root))
    else:  # EDSL 1.0.8
        monkeypatch.setattr(ObjectStore, "DEFAULT_ROOT", root)
    monkeypatch.setattr(CONFIG, "EDSL_FETCH_TOKEN_PRICES", "False", raising=False)

    def forbid_network(*args, **kwargs):
        pytest.fail("Offline EDSL tests must not contact a remote service")

    monkeypatch.setattr(socket, "getaddrinfo", forbid_network)
    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid_network)


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
