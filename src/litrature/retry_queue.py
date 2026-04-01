from __future__ import annotations

from pathlib import Path

from .io_utils import read_jsonl, write_jsonl


def append_failure(queue_path: Path, payload: dict) -> None:
    rows = read_jsonl(queue_path)
    rows.append(payload)
    write_jsonl(queue_path, rows)
