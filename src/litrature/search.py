from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

from .config import ResearchProfile


@dataclass
class SearchOptions:
    source: str = "crossref"
    limit: int = 20
    max_total: int = 100
    timeout_seconds: int = 20


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return unescape(clean)


def _build_crossref_url(query: str, limit: int) -> str:
    return (
        "https://api.crossref.org/works"
        f"?query.bibliographic={quote(query)}"
        "&sort=published&order=desc"
        f"&rows={limit}"
    )


def _build_serpapi_scholar_url(query: str, limit: int, api_key: str) -> str:
    return (
        "https://serpapi.com/search.json"
        "?engine=google_scholar"
        f"&q={quote(query)}"
        f"&num={limit}"
        f"&api_key={quote(api_key)}"
    )


def _first_year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        block = item.get(key)
        if not isinstance(block, dict):
            continue
        parts = block.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
            if isinstance(value, int):
                return value
    return None


def _parse_crossref_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    message = payload.get("message", {})
    items = message.get("items", [])
    rows: list[dict[str, Any]] = []

    for item in items:
        title_list = item.get("title") or []
        title = str(title_list[0]).strip() if title_list else ""
        abstract = _strip_html(str(item.get("abstract", "")))

        journal_list = item.get("container-title") or []
        journal = str(journal_list[0]).strip() if journal_list else ""

        doi = str(item.get("DOI", "")).strip()
        url = str(item.get("URL", "")).strip()
        pdf_url = ""
        links = item.get("link") or []
        for link in links:
            if not isinstance(link, dict):
                continue
            content_type = str(link.get("content-type", "")).lower()
            if "pdf" in content_type:
                pdf_url = str(link.get("URL", "")).strip()
                break

        row = {
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "year": _first_year(item),
            "doi": doi,
            "source": "crossref",
            "source_url": url,
            "pdf_url": pdf_url,
        }
        if not _is_domain_relevant(row):
            continue
        rows.append(row)

    return rows


def _parse_serpapi_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("organic_results", [])
    rows: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return rows

    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        link = str(item.get("link", "")).strip()

        publication_info = item.get("publication_info", {})
        summary = ""
        if isinstance(publication_info, dict):
            summary = str(publication_info.get("summary", "")).strip()

        journal = ""
        year: int | None = None
        if summary:
            parts = [p.strip() for p in summary.split("-") if p.strip()]
            if parts:
                journal = parts[0]
            m = re.search(r"\b(19|20)\d{2}\b", summary)
            if m:
                year = int(m.group(0))

        doi = ""
        resources = item.get("resources", [])
        pdf_url = ""
        if isinstance(resources, list):
            for res in resources:
                if not isinstance(res, dict):
                    continue
                res_link = str(res.get("link", "")).strip()
                if res_link.lower().endswith(".pdf"):
                    pdf_url = res_link
                    break

        row = {
            "title": title,
            "abstract": snippet,
            "journal": journal,
            "year": year,
            "doi": doi,
            "source": "google_scholar",
            "source_url": link,
            "pdf_url": pdf_url,
        }
        if not _is_domain_relevant(row):
            continue
        rows.append(row)

    return rows


def _apply_journal_policy(rows: list[dict[str, Any]], profile: ResearchProfile) -> list[dict[str, Any]]:
    policy = profile.journal_policy or {}
    whitelist = {str(v).strip().lower() for v in policy.get("whitelist", []) if str(v).strip()}
    blacklist = {str(v).strip().lower() for v in policy.get("blacklist", []) if str(v).strip()}
    require_whitelist = bool(policy.get("require_whitelist_match", False))

    filtered: list[dict[str, Any]] = []
    for row in rows:
        journal = str(row.get("journal", "")).strip().lower()
        if journal and journal in blacklist:
            continue
        if require_whitelist and whitelist and journal not in whitelist:
            continue

        if journal in whitelist:
            row["journal_policy"] = "whitelist"
        elif journal in blacklist:
            row["journal_policy"] = "blacklist"
        else:
            row["journal_policy"] = "neutral"
        filtered.append(row)

    return filtered


def _is_domain_relevant(row: dict[str, Any]) -> bool:
    text = f"{row.get('title', '')}\n{row.get('abstract', '')}".lower()

    positive_hints = (
        "battery",
        "zinc-ion",
        "zn-ion",
        "aqueous",
        "anode",
        "electrolyte",
        "plating",
        "stripping",
        "dendrite",
        "her",
        "coulombic",
        "solvation",
        "desolvation",
        "nucleation",
    )
    if not any(h in text for h in positive_hints):
        return False

    negative_hints = (
        "mice",
        "mouse",
        "rat",
        "veterinary",
        "infection",
        "osteosarcoma",
        "drug delivery",
        "chicken",
        "photocatalyst",
        "parasite",
    )
    if any(h in text for h in negative_hints):
        return False

    return True


def _build_query_list(profile: ResearchProfile) -> list[str]:
    strategy = profile.search_strategy or {}
    queries = strategy.get("queries")
    if isinstance(queries, list):
        collected = [str(q).strip() for q in queries if str(q).strip()]
        if collected:
            return collected

    query = profile.search_query_core.strip()
    if query:
        return [query]

    return []


def _row_key(row: dict[str, Any]) -> str:
    doi = str(row.get("doi", "")).strip().lower()
    if doi:
        return f"doi:{doi}"
    title = str(row.get("title", "")).strip().lower()
    year = str(row.get("year", "")).strip()
    return f"title:{title}|{year}"


def search_candidates(profile: ResearchProfile, options: SearchOptions) -> list[dict[str, Any]]:
    query_list = _build_query_list(profile)
    if not query_list:
        raise ValueError("研究画像中的检索式为空")

    source = options.source.lower().strip()
    if source not in ("crossref", "google_scholar", "mixed"):
        raise ValueError(f"暂不支持的检索源: {options.source}")

    if source == "mixed":
        source_chain = ["crossref", "google_scholar"]
    else:
        source_chain = [source]

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    serpapi_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if "google_scholar" in source_chain and not serpapi_key:
        raise ValueError("source=google_scholar 或 mixed 需要环境变量 SERPAPI_API_KEY")

    for query in query_list:
        for source_name in source_chain:
            if source_name == "crossref":
                url = _build_crossref_url(query=query, limit=options.limit)
            else:
                url = _build_serpapi_scholar_url(query=query, limit=options.limit, api_key=serpapi_key)

            with urlopen(url, timeout=options.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))

            if source_name == "crossref":
                parsed = _parse_crossref_items(payload)
            else:
                parsed = _parse_serpapi_items(payload)

            parsed_rows = _apply_journal_policy(parsed, profile)
            for row in parsed_rows:
                row["matched_query"] = query
                row["source"] = source_name
                key = _row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(row)
                if len(merged) >= options.max_total:
                    return merged

    return merged
