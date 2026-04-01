from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ResearchProfile:
    name: str
    domain: str
    topics: list[str]
    must_have_terms: list[str]
    exclude_terms: list[str]
    target_journals: dict[str, list[str]]
    mechanism_questions: list[str]
    search_query_core: str
    search_strategy: dict[str, Any]
    journal_policy: dict[str, Any]
    quality_gate: dict[str, Any]


@dataclass
class AppConfig:
    workspace: Path
    profile_path: Path
    data_dir: Path
    logs_dir: Path


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"YAML 根节点格式无效: {path}")
    return data


def load_profile(profile_path: Path) -> ResearchProfile:
    raw = load_yaml(profile_path)
    profile = raw.get("profile", {})
    return ResearchProfile(
        name=str(profile.get("name", "default-profile")),
        domain=str(profile.get("domain", "")),
        topics=[str(v) for v in raw.get("topics", [])],
        must_have_terms=[str(v) for v in raw.get("must_have_terms", [])],
        exclude_terms=[str(v) for v in raw.get("exclude_terms", [])],
        target_journals={
            str(k): [str(v) for v in vals]
            for k, vals in raw.get("target_journals", {}).items()
        },
        mechanism_questions=[str(v) for v in raw.get("mechanism_questions", [])],
        search_query_core=str(raw.get("search_query_core", "")),
        search_strategy=dict(raw.get("search_strategy", {})),
        journal_policy=dict(raw.get("journal_policy", {})),
        quality_gate=dict(raw.get("quality_gate", {})),
    )


def build_app_config(workspace: Path, profile_relpath: str = "configs/research_profile.yaml") -> AppConfig:
    workspace = workspace.resolve()
    return AppConfig(
        workspace=workspace,
        profile_path=workspace / profile_relpath,
        data_dir=workspace / "data",
        logs_dir=workspace / "logs",
    )
