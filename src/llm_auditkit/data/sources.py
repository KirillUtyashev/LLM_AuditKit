"""Local and remote implementations of the dataset source boundary."""

from __future__ import annotations

import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import pandas as pd

from .exceptions import DatasetConfigurationError, DatasetSourceError
from .formats import (
    has_supported_extension,
    infer_file_format,
    normalize_file_format,
    read_tabular_bytes,
)
from .models import RemoteConfig


@runtime_checkable
class DatasetSource(Protocol):
    """A caller-extensible source of one raw tabular DataFrame."""

    def load(self) -> pd.DataFrame:
        """Read the source into a raw DataFrame."""


@dataclass(frozen=True, slots=True)
class LocalDatasetSource:
    """Read one supported local file or deterministic same-schema directory."""

    path: str | Path
    file_format: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, (str, Path)) or not str(self.path).strip():
            raise DatasetConfigurationError(
                "local dataset path must be a non-empty string or Path"
            )
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(
            self,
            "file_format",
            normalize_file_format(self.file_format),
        )

    def load(self) -> pd.DataFrame:
        """Read the configured local file or directory."""

        if self.path.is_file():
            return self._load_file(self.path, self.file_format)
        if self.path.is_dir():
            if self.file_format is not None:
                raise DatasetConfigurationError(
                    "file_format cannot be set for a local dataset directory"
                )
            return self._load_directory()
        raise DatasetSourceError(
            f"local dataset path does not exist: {self.path}"
        )

    def _load_directory(self) -> pd.DataFrame:
        try:
            files = sorted(
                (
                    entry
                    for entry in self.path.iterdir()
                    if entry.is_file() and has_supported_extension(entry)
                ),
                key=lambda entry: (entry.name.casefold(), entry.name),
            )
        except OSError as error:
            raise DatasetSourceError(
                f"could not inspect local dataset directory {self.path}: "
                f"{type(error).__name__}: {error}"
            ) from error
        if not files:
            raise DatasetSourceError(
                "local dataset directory contains no supported files"
            )

        frames = [self._load_file(path, None) for path in files]
        expected_columns = list(frames[0].columns)
        expected_set = set(expected_columns)
        aligned = [frames[0]]
        for path, frame in zip(files[1:], frames[1:], strict=True):
            if set(frame.columns) != expected_set:
                raise DatasetSourceError(
                    f"dataset file {path.name!r} does not match the directory schema"
                )
            aligned.append(frame[expected_columns])
        return pd.concat(aligned, ignore_index=True)

    @staticmethod
    def _load_file(path: Path, file_format: str | None) -> pd.DataFrame:
        resolved_format = file_format or infer_file_format(path)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise DatasetSourceError(
                f"could not read local dataset file {path}: "
                f"{type(error).__name__}: {error}"
            ) from error
        return read_tabular_bytes(
            data,
            resolved_format,
            source_label=f"local dataset file {path}",
        )


@dataclass(frozen=True, slots=True)
class RemoteDatasetSource:
    """Download one bounded HTTP(S) table and parse it in memory."""

    config: RemoteConfig

    def __post_init__(self) -> None:
        _validate_remote_config(self.config)

    def load(self) -> pd.DataFrame:
        """Download and parse the configured remote dataset."""

        config = self.config
        _validate_remote_config(config)
        parsed_url = urlsplit(config.url)
        file_format = normalize_file_format(config.file_format)
        if file_format is None:
            file_format = infer_file_format(parsed_url.path)

        headers = {"User-Agent": "LLM-AuditKit"}
        if config.credential_env is not None:
            credential = os.environ.get(config.credential_env)
            if credential is None or not credential.strip():
                raise DatasetSourceError(
                    f"remote credential environment variable "
                    f"{config.credential_env!r} is not set"
                )
            headers["Authorization"] = f"Bearer {credential}"

        request = urllib.request.Request(config.url, headers=headers)
        try:
            with urllib.request.urlopen(
                request,
                timeout=config.timeout_seconds,
            ) as response:
                content_length = response.headers.get("Content-Length")
                if (
                    content_length is not None
                    and int(content_length) > config.max_bytes
                ):
                    raise DatasetSourceError(
                        "remote dataset exceeds configured max_bytes"
                    )
                data = response.read(config.max_bytes + 1)
        except DatasetSourceError:
            raise
        except urllib.error.HTTPError as error:
            raise DatasetSourceError(
                f"remote dataset request failed with HTTP status {error.code}"
            ) from error
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise DatasetSourceError(
                f"could not download remote dataset: {type(error).__name__}"
            ) from error

        if len(data) > config.max_bytes:
            raise DatasetSourceError("remote dataset exceeds configured max_bytes")
        return read_tabular_bytes(
            data,
            file_format,
            source_label="remote dataset",
            expose_error_details=False,
        )


def _validate_remote_config(config: RemoteConfig) -> None:
    if not isinstance(config, RemoteConfig):
        raise DatasetConfigurationError("config must be a RemoteConfig")
    if config.backend != "http":
        raise DatasetConfigurationError("remote backend must be 'http'")
    if not isinstance(config.url, str) or not config.url.strip():
        raise DatasetConfigurationError("remote url must be a non-empty string")
    parsed = urlsplit(config.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DatasetConfigurationError(
            "remote url must be an absolute HTTP(S) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise DatasetConfigurationError(
            "remote url must not contain embedded credentials"
        )
    normalize_file_format(config.file_format)
    if config.credential_env is not None and (
        not isinstance(config.credential_env, str)
        or not config.credential_env.strip()
    ):
        raise DatasetConfigurationError(
            "credential_env must be a non-empty string or None"
        )
    if (
        isinstance(config.timeout_seconds, bool)
        or not isinstance(config.timeout_seconds, (int, float))
        or not math.isfinite(config.timeout_seconds)
        or config.timeout_seconds <= 0
    ):
        raise DatasetConfigurationError(
            "timeout_seconds must be a positive finite number"
        )
    if (
        isinstance(config.max_bytes, bool)
        or not isinstance(config.max_bytes, int)
        or config.max_bytes <= 0
    ):
        raise DatasetConfigurationError("max_bytes must be a positive integer")
