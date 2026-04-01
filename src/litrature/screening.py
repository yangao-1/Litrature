from __future__ import annotations

from dataclasses import dataclass

from .config import ResearchProfile


@dataclass
class CandidateRecord:
    title: str
    abstract: str
    journal: str
    year: int | None = None


@dataclass
class ScreeningResult:
    keep: bool
    score: float
    method_hits: list[str]
    exclude_hits: list[str]
    journal_tier: str
    reasons: list[str]


def _lower(text: str) -> str:
    return text.lower()


def _find_hits(text: str, terms: list[str]) -> list[str]:
    lowered = _lower(text)
    hits: list[str] = []
    for term in terms:
        if _lower(term) in lowered:
            hits.append(term)
    return hits


def _journal_tier(journal: str, tiers: dict[str, list[str]]) -> str:
    j = _lower(journal)
    for tier_name in ("tier_1", "tier_2", "tier_3"):
        for expected in tiers.get(tier_name, []):
            if _lower(expected) == j:
                return tier_name
    return "unranked"


def screen_candidate(record: CandidateRecord, profile: ResearchProfile) -> ScreeningResult:
    text = f"{record.title}\n{record.abstract}"
    abstract_text = record.abstract.strip()
    method_hits = _find_hits(text, profile.must_have_terms)
    exclude_hits = _find_hits(text, profile.exclude_terms)
    journal_tier = _journal_tier(record.journal, profile.target_journals)

    minimum_hits = int(profile.quality_gate.get("minimum_method_hits", 2))
    require_mech = bool(profile.quality_gate.get("require_mechanism_evidence", True))

    reasons: list[str] = []
    score = 0.0

    if journal_tier == "tier_1":
        score += 2.0
    elif journal_tier == "tier_2":
        score += 1.2
    elif journal_tier == "tier_3":
        score += 0.6

    score += min(3.0, 0.5 * len(method_hits))
    score -= min(3.0, 0.7 * len(exclude_hits))

    if len(method_hits) >= minimum_hits:
        reasons.append("方法学证据达到阈值")
    else:
        reasons.append("方法学证据不足")

    if exclude_hits:
        reasons.append("命中排除词")

    title_lower = _lower(record.title)
    topic_hint_hits = 0
    for hint in (
        "zinc",
        "zn",
        "anode",
        "electrolyte",
        "interface",
        "solvation",
        "desolvation",
        "her",
        "dendrite",
        "hydrogel",
        "polymer",
        "acetate",
        "ammonia",
        "nh3",
    ):
        if hint in title_lower:
            topic_hint_hits += 1

    keep = True
    if require_mech and len(method_hits) < minimum_hits:
        keep = False
    if exclude_hits:
        keep = False

    # Crossref 常出现无摘要记录，先低置信保留主题相关条目，后续由人工或全文步骤复核。
    if not abstract_text and not exclude_hits and topic_hint_hits >= 2:
        keep = True
        reasons.append("摘要缺失，按主题相关性低置信保留")

    # 对 tier_1/tier_2 且主题命中较高但方法词不足的条目，给一次保留机会。
    if (
        keep is False
        and not exclude_hits
        and journal_tier in ("tier_1", "tier_2")
        and topic_hint_hits >= 3
        and len(method_hits) >= 1
    ):
        keep = True
        reasons.append("高层级期刊且主题相关，暂保留待复核")

    if keep:
        reasons.append("通过规则门控")
    else:
        reasons.append("未通过规则门控")

    return ScreeningResult(
        keep=keep,
        score=round(score, 3),
        method_hits=method_hits,
        exclude_hits=exclude_hits,
        journal_tier=journal_tier,
        reasons=reasons,
    )
