"""Local implementations of the dataset source boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from .exceptions import DatasetConfigurationError, DatasetSourceError
from .formats import (
    has_supported_extension,
    infer_file_format,
    normalize_file_format,
    read_tabular_bytes,
)


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
