from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def normalize_title(title: str) -> str:
    text = title.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_key(row: dict) -> str:
    doi = str(row.get("doi", "")).strip().lower()
    if doi:
        return f"doi:{doi}"

    title = normalize_title(str(row.get("title", "")))
    year = str(row.get("year", "")).strip()
    raw = f"{title}|{year}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"title:{digest}"


def load_index(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return data


def save_index(path: Path, data: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def deduplicate_rows(rows: list[dict], index_path: Path) -> tuple[list[dict], list[dict], dict[str, dict]]:
    index = load_index(index_path)

    unique_rows: list[dict] = []
    duplicate_rows: list[dict] = []

    for row in rows:
        key = build_key(row)
        row["dedup_key"] = key
        if key in index:
            duplicate_rows.append(row)
            continue

        index[key] = {
            "title": str(row.get("title", "")),
            "year": row.get("year"),
            "doi": str(row.get("doi", "")),
        }
        unique_rows.append(row)

    return unique_rows, duplicate_rows, index
