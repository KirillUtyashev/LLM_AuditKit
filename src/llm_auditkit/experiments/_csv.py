"""Read experiment CSVs without interpreting or truncating text fields."""

from io import StringIO
from pathlib import Path
from typing import TextIO

import pandas as pd


def read_text_csv(source: Path | StringIO) -> pd.DataFrame:
    if isinstance(source, Path):
        with source.open(encoding="utf-8", newline="") as file:
            return _read_stream(file)
    return _read_stream(source)


def _read_stream(stream: TextIO) -> pd.DataFrame:
    # Keep ordinary checkpoints on pandas' streaming path. Check in chunks so
    # a second copy of a large file is only needed if it contains a NUL.
    stream.seek(0)
    has_nul = any("\0" in chunk for chunk in iter(lambda: stream.read(1024 * 1024), ""))
    stream.seek(0)
    if not has_nul:
        return pd.read_csv(stream, dtype="string", keep_default_na=False)

    # pandas' C parser truncates at NUL. Encode it only during parsing so
    # long fields and quoted carriage returns retain their original text.
    text = stream.read()
    marker = "<AuditKit-NUL>"
    while marker in text:
        marker = marker[:-1] + "_>"
    text = text.replace("\0", marker)
    frame = pd.read_csv(StringIO(text, newline=""), dtype="string", keep_default_na=False)
    for column in frame.columns:
        frame[column] = frame[column].str.replace(marker, "\0", regex=False)
    frame.columns = [name.replace(marker, "\0") for name in frame.columns]
    return frame
