"""Offline tests for bounded HTTP(S) dataset sources."""

from __future__ import annotations

import urllib.error
from collections.abc import Callable

import pandas as pd
import pytest

from llm_auditkit.data import (
    DatasetConfigurationError,
    DatasetSourceError,
    RemoteConfig,
    RemoteDatasetSource,
)


class FakeResponse:
    def __init__(self, data: bytes, *, content_length: str | None = None) -> None:
        self._data = data
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self._data[:size]


def _patch_response(
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse,
) -> list[tuple[object, float]]:
    calls: list[tuple[object, float]] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        calls.append((request, timeout))
        return response

    monkeypatch.setattr(
        "llm_auditkit.data.sources.urllib.request.urlopen",
        fake_urlopen,
    )
    return calls


def test_remote_source_infers_format_and_sends_bearer_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_response(
        monkeypatch,
        FakeResponse(b"job,code\nPosting,00007\n"),
    )
    monkeypatch.setenv("AUDIT_DATA_TOKEN", "secret-value")
    source = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv?version=1",
            credential_env="AUDIT_DATA_TOKEN",
            timeout_seconds=4.5,
        )
    )

    frame = source.load()

    assert frame.iloc[0].to_dict() == {"job": "Posting", "code": "00007"}
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.get_header("Authorization") == "Bearer secret-value"
    assert timeout == 4.5


def test_remote_source_supports_explicit_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_response(monkeypatch, FakeResponse(b'{"job":"Posting"}\n'))
    source = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/download",
            file_format="jsonl",
        )
    )

    frame = source.load()

    assert isinstance(frame, pd.DataFrame)
    assert frame["job"].tolist() == ["Posting"]


def test_missing_credential_fails_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_urlopen(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.delenv("MISSING_DATA_TOKEN", raising=False)
    monkeypatch.setattr(
        "llm_auditkit.data.sources.urllib.request.urlopen",
        unexpected_urlopen,
    )
    source = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv",
            credential_env="MISSING_DATA_TOKEN",
        )
    )

    with pytest.raises(DatasetSourceError, match="MISSING_DATA_TOKEN"):
        source.load()

    assert called is False


@pytest.mark.parametrize(
    "config_factory",
    [
        lambda: RemoteConfig(backend="s3", url="https://example.test/jobs.csv"),
        lambda: RemoteConfig(backend="http", url="file:///tmp/jobs.csv"),
        lambda: RemoteConfig(
            backend="http",
            url="https://user:pass@example.test/jobs.csv",
        ),
        lambda: RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv",
            timeout_seconds=0,
        ),
        lambda: RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv",
            max_bytes=True,
        ),
        lambda: RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv",
            file_format="parquet",
        ),
    ],
)
def test_invalid_remote_configuration_is_rejected(
    config_factory: Callable[[], RemoteConfig],
) -> None:
    with pytest.raises(DatasetConfigurationError):
        RemoteDatasetSource(config_factory())


def test_response_size_is_bounded_before_and_during_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv",
            max_bytes=5,
        )
    )
    _patch_response(monkeypatch, FakeResponse(b"job\n", content_length="6"))
    with pytest.raises(DatasetSourceError, match="max_bytes"):
        declared.load()

    streamed = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv",
            max_bytes=5,
        )
    )
    _patch_response(monkeypatch, FakeResponse(b"1234567"))
    with pytest.raises(DatasetSourceError, match="max_bytes"):
        streamed.load()


def test_transport_error_does_not_repeat_the_url_or_query_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError("https://example.test/jobs.csv?token=secret")

    monkeypatch.setattr(
        "llm_auditkit.data.sources.urllib.request.urlopen",
        fail,
    )
    source = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/jobs.csv?token=secret",
        )
    )

    with pytest.raises(DatasetSourceError) as captured:
        source.load()

    assert "secret" not in str(captured.value)
    assert "URLError" in str(captured.value)


def test_remote_parse_error_does_not_repeat_response_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_response(
        monkeypatch,
        FakeResponse(b'[{"private_field":"one","private_field":"two"}]'),
    )
    source = RemoteDatasetSource(
        RemoteConfig(
            backend="http",
            url="https://example.test/jobs.json",
        )
    )

    with pytest.raises(DatasetSourceError) as captured:
        source.load()

    assert "private_field" not in str(captured.value)
    assert "could not parse remote dataset as json" in str(captured.value)
