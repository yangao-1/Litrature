from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass
class ZoteroConfig:
    user_id: str
    api_key: str
    library_type: str = "users"


def _build_endpoint(cfg: ZoteroConfig) -> str:
    return f"https://api.zotero.org/{cfg.library_type}/{cfg.user_id}/items"


def _build_item(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title", "")).strip()
    abstract_note = str(row.get("abstract", "")).strip()
    journal = str(row.get("journal", "")).strip()
    doi = str(row.get("doi", "")).strip()
    year = row.get("year")

    item = {
        "itemType": "journalArticle",
        "title": title,
        "abstractNote": abstract_note,
        "publicationTitle": journal,
        "date": str(year) if year else "",
        "DOI": doi,
        "url": str(row.get("source_url", "")).strip(),
        "tags": [{"tag": "auto-import"}],
        "collections": [],
    }
    return item


def create_item(cfg: ZoteroConfig, row: dict[str, Any], timeout_seconds: int = 20) -> dict[str, Any]:
    endpoint = _build_endpoint(cfg)
    payload = [_build_item(row)]

    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Zotero-API-Key": cfg.api_key,
            "Zotero-Write-Token": "litrature-auto",
        },
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            text = resp.read().decode("utf-8")
            parent_resp = {"ok": True, "status": resp.status, "body": text}

            pdf_url = str(row.get("pdf_url", "")).strip()
            if not pdf_url:
                return parent_resp

            parent_key = _extract_success_key(text)
            if not parent_key:
                return {
                    **parent_resp,
                    "attachment": {"ok": False, "status": 0, "body": "未提取到 parent key"},
                }

            attachment = _create_attachment(
                cfg=cfg,
                parent_key=parent_key,
                pdf_url=pdf_url,
                timeout_seconds=timeout_seconds,
            )
            return {**parent_resp, "attachment": attachment}
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return {"ok": False, "status": e.code, "body": body}


def _extract_success_key(response_text: str) -> str:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return ""

    successful = payload.get("successful", {})
    if not isinstance(successful, dict):
        return ""

    for value in successful.values():
        if not isinstance(value, dict):
            continue
        data = value.get("data", {})
        if not isinstance(data, dict):
            continue
        key = str(data.get("key", "")).strip()
        if key:
            return key
    return ""


def _create_attachment(cfg: ZoteroConfig, parent_key: str, pdf_url: str, timeout_seconds: int) -> dict[str, Any]:
    endpoint = _build_endpoint(cfg)
    payload = [
        {
            "itemType": "attachment",
            "parentItem": parent_key,
            "linkMode": "linked_url",
            "title": "PDF",
            "url": pdf_url,
            "contentType": "application/pdf",
        }
    ]
    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Zotero-API-Key": cfg.api_key,
            "Zotero-Write-Token": "litrature-attach",
        },
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            return {"ok": True, "status": resp.status, "body": resp.read().decode("utf-8")}
    except HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode("utf-8", errors="ignore")}


def dry_run_item(row: dict[str, Any]) -> dict[str, Any]:
    item = _build_item(row)
    return {
        "ok": True,
        "status": 0,
        "body": "dry-run",
        "preview": item,
    }
