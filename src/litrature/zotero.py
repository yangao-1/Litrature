from __future__ import annotations

from html import escape, unescape
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass
class ZoteroConfig:
    user_id: str
    api_key: str
    library_type: str = "users"
    backend: str = "api"


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
    if cfg.backend == "mcp":
        return _create_item_via_mcp(cfg=cfg, row=row, timeout_seconds=timeout_seconds)

    endpoint = _build_endpoint(cfg)
    payload = [_build_item(row)]

    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Zotero-API-Key": cfg.api_key,
            "Zotero-Write-Token": _new_write_token("litrature-auto"),
        },
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            text = resp.read().decode("utf-8")
            parent_key = extract_success_key(text)
            parent_resp = {
                "ok": True,
                "status": resp.status,
                "body": text,
                "parent_key": parent_key,
            }

            pdf_url = _resolve_pdf_url(row, timeout_seconds=timeout_seconds)
            if not pdf_url:
                note = _create_ai_note(
                    cfg=cfg,
                    parent_key=parent_key,
                    row=row,
                    timeout_seconds=timeout_seconds,
                )
                return {
                    **parent_resp,
                    "attachment": {"ok": False, "status": 0, "body": "未找到可用 PDF 链接"},
                    "note": note,
                }

            if not parent_key:
                return {
                    **parent_resp,
                    "attachment": {"ok": False, "status": 0, "body": "未提取到 parent key"},
                    "note": {"ok": False, "status": 0, "body": "未提取到 parent key，无法创建笔记"},
                }

            attachment = _create_attachment(
                cfg=cfg,
                parent_key=parent_key,
                pdf_url=pdf_url,
                timeout_seconds=timeout_seconds,
            )
            note = _create_ai_note(
                cfg=cfg,
                parent_key=parent_key,
                row=row,
                timeout_seconds=timeout_seconds,
            )
            return {**parent_resp, "attachment": attachment, "note": note}
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return {"ok": False, "status": e.code, "body": body}


def _create_item_via_mcp(cfg: ZoteroConfig, row: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    endpoint = os.getenv("ZOTERO_MCP_ENDPOINT", "").strip()
    method = os.getenv("ZOTERO_MCP_METHOD", "zotero.create_item").strip()
    if not endpoint:
        return {"ok": False, "status": 0, "body": "缺少环境变量 ZOTERO_MCP_ENDPOINT"}

    note_html = _build_note_summary(row, timeout_seconds=timeout_seconds)
    request_payload = {
        "jsonrpc": "2.0",
        "id": "litrature-zotero",
        "method": method,
        "params": {
            "item": _build_item(row),
            "row": row,
            "attach_pdf": True,
            "local_pdf_path": str(row.get("local_pdf_path", "")).strip(),
            "note_html": note_html,
        },
    }

    headers = {"Content-Type": "application/json"}
    mcp_token = os.getenv("ZOTERO_MCP_TOKEN", "").strip()
    if mcp_token:
        headers["Authorization"] = f"Bearer {mcp_token}"

    req = Request(
        endpoint,
        data=json.dumps(request_payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            text = resp.read().decode("utf-8")
    except HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode("utf-8", errors="ignore")}
    except Exception as e:
        return {"ok": False, "status": 0, "body": f"MCP 调用失败: {e}"}

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": True, "status": 200, "body": text}

    if isinstance(payload, dict) and payload.get("error"):
        return {"ok": False, "status": 0, "body": json.dumps(payload.get("error"), ensure_ascii=False)}

    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, list) and result and isinstance(result[0], dict):
        result = result[0]

    if not isinstance(result, dict):
        return {"ok": True, "status": 200, "body": text}

    return _normalize_mcp_result(result=result, raw_text=text)


def _normalize_mcp_result(result: dict[str, Any], raw_text: str) -> dict[str, Any]:
    status = _safe_int(result.get("status", result.get("statusCode", 200)), 200)
    parent_key = str(
        result.get("parent_key", "")
        or result.get("itemKey", "")
        or result.get("key", "")
        or (result.get("item", {}) or {}).get("key", "")
    ).strip()

    attachment = _normalize_mcp_child_status(
        raw=result,
        child_key="attachment",
        ok_key="attachment_ok",
        status_key="attachment_status",
        body_key="attachment_body",
    )
    note = _normalize_mcp_child_status(
        raw=result,
        child_key="note",
        ok_key="note_ok",
        status_key="note_status",
        body_key="note_body",
    )

    top_ok = bool(result.get("ok", status < 400))
    return {
        "ok": top_ok,
        "status": status,
        "body": raw_text,
        "parent_key": parent_key,
        "attachment": attachment,
        "note": note,
    }


def _normalize_mcp_child_status(
    raw: dict[str, Any],
    child_key: str,
    ok_key: str,
    status_key: str,
    body_key: str,
) -> dict[str, Any]:
    child = raw.get(child_key)
    if isinstance(child, dict):
        return {
            "ok": bool(child.get("ok", False)),
            "status": _safe_int(child.get("status", 0), 0),
            "body": str(child.get("body", "")),
        }

    return {
        "ok": bool(raw.get(ok_key, False)),
        "status": _safe_int(raw.get(status_key, 0), 0),
        "body": str(raw.get(body_key, "")),
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def extract_success_key(response_text: str) -> str:
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
    payload = [_build_attachment_item(parent_key=parent_key, pdf_url=pdf_url, link_mode="linked_url")]
    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Zotero-API-Key": cfg.api_key,
            "Zotero-Write-Token": _new_write_token("litrature-attach"),
        },
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            return {"ok": True, "status": resp.status, "body": resp.read().decode("utf-8")}
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return {"ok": False, "status": e.code, "body": body}


def _build_attachment_item(parent_key: str, pdf_url: str, link_mode: str) -> dict[str, str]:
    return {
        "itemType": "attachment",
        "parentItem": parent_key,
        "linkMode": link_mode,
        "title": "PDF",
        "url": pdf_url,
        "contentType": "application/pdf",
    }


def _create_ai_note(cfg: ZoteroConfig, parent_key: str, row: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    if not parent_key:
        return {"ok": False, "status": 0, "body": "parent key 为空"}

    summary = _build_note_summary(row, timeout_seconds=timeout_seconds)
    endpoint = _build_endpoint(cfg)
    payload = [
        {
            "itemType": "note",
            "parentItem": parent_key,
            "note": summary,
        }
    ]
    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Zotero-API-Key": cfg.api_key,
            "Zotero-Write-Token": _new_write_token("litrature-note"),
        },
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            return {"ok": True, "status": resp.status, "body": resp.read().decode("utf-8")}
    except HTTPError as e:
        return {"ok": False, "status": e.code, "body": e.read().decode("utf-8", errors="ignore")}


def _build_note_summary(row: dict[str, Any], timeout_seconds: int) -> str:
    try:
        from .summarizer import generate_note_markdown

        markdown = generate_note_markdown(row, timeout_seconds=min(timeout_seconds, 20))
    except Exception:
        markdown = "自动总结失败，请查看原文。"

    title = escape(str(row.get("title", "")).strip())
    doi = escape(str(row.get("doi", "")).strip())
    content = escape(markdown)
    return (
        f"<h2>AI 结构化笔记</h2>"
        f"<p><b>Title:</b> {title}</p>"
        f"<p><b>DOI:</b> {doi}</p>"
        f"<pre>{content}</pre>"
    )


def _resolve_pdf_url(row: dict[str, Any], timeout_seconds: int) -> str:
    pdf_url = str(row.get("pdf_url", "")).strip()
    if pdf_url:
        return pdf_url

    source_url = str(row.get("source_url", "")).strip()
    if source_url.lower().endswith(".pdf"):
        return source_url

    source_guess = _resolve_pdf_from_landing_page(source_url=source_url, timeout_seconds=timeout_seconds)
    if source_guess:
        return source_guess

    doi = str(row.get("doi", "")).strip()
    if not doi:
        return ""

    for resolver in (
        _resolve_pdf_from_openalex,
        _resolve_pdf_from_unpaywall,
        _resolve_pdf_from_doi_redirect,
    ):
        candidate = resolver(doi=doi, timeout_seconds=timeout_seconds)
        if candidate:
            return candidate

    return ""


def resolve_pdf_url(row: dict[str, Any], timeout_seconds: int = 20) -> str:
    return _resolve_pdf_url(row=row, timeout_seconds=timeout_seconds)


def _resolve_pdf_from_openalex(doi: str, timeout_seconds: int) -> str:
    doi_path = quote(f"https://doi.org/{doi}", safe="")
    url = f"https://api.openalex.org/works/{doi_path}"
    req = Request(url, method="GET", headers={"User-Agent": "litrature-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return ""

    best = data.get("best_oa_location", {})
    if isinstance(best, dict):
        best_pdf = str(best.get("pdf_url", "")).strip()
        if best_pdf:
            return best_pdf

    primary = data.get("primary_location", {})
    if isinstance(primary, dict):
        primary_pdf = str(primary.get("pdf_url", "")).strip()
        if primary_pdf:
            return primary_pdf

    locations = data.get("locations", [])
    if isinstance(locations, list):
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            candidate = str(loc.get("pdf_url", "")).strip()
            if candidate:
                return candidate

    return ""


def _resolve_pdf_from_unpaywall(doi: str, timeout_seconds: int) -> str:
    email = os.getenv("UNPAYWALL_EMAIL", "").strip()
    if not email:
        return ""

    url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={quote(email)}"
    req = Request(url, method="GET", headers={"User-Agent": "litrature-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return ""

    best = data.get("best_oa_location", {})
    if isinstance(best, dict):
        best_pdf = str(best.get("url_for_pdf", "")).strip()
        if best_pdf:
            return best_pdf

    locations = data.get("oa_locations", [])
    if isinstance(locations, list):
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            candidate = str(loc.get("url_for_pdf", "")).strip()
            if candidate:
                return candidate

    return ""


def _resolve_pdf_from_doi_redirect(doi: str, timeout_seconds: int) -> str:
    doi_url = f"https://doi.org/{quote(doi)}"
    req = Request(
        doi_url,
        method="GET",
        headers={
            "User-Agent": "litrature-bot/1.0",
            "Accept": "application/pdf,text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            final_url = str(resp.geturl()).strip()
            content_type = str(resp.headers.get("Content-Type", "")).lower()
            html = ""
            if "text/html" in content_type:
                html = resp.read(200_000).decode("utf-8", errors="ignore")
    except Exception:
        return ""

    if final_url.lower().endswith(".pdf"):
        return final_url
    if "application/pdf" in content_type:
        return final_url
    if html:
        return _extract_pdf_link_from_html(html=html, base_url=final_url)
    return ""


def _resolve_pdf_from_landing_page(source_url: str, timeout_seconds: int) -> str:
    if not source_url:
        return ""
    req = Request(source_url, method="GET", headers={"User-Agent": "litrature-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            final_url = str(resp.geturl()).strip()
            content_type = str(resp.headers.get("Content-Type", "")).lower()
            if "application/pdf" in content_type or final_url.lower().endswith(".pdf"):
                return final_url
            if "text/html" not in content_type:
                return ""
            html = resp.read(200_000).decode("utf-8", errors="ignore")
    except Exception:
        return ""

    return _extract_pdf_link_from_html(html=html, base_url=final_url)


def _extract_pdf_link_from_html(html: str, base_url: str) -> str:
    for pat in (
        r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
        r'content=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
    ):
        m = re.search(pat, html, flags=re.IGNORECASE)
        if not m:
            continue
        raw = unescape(m.group(1)).strip()
        if not raw:
            continue
        return urljoin(base_url, raw)
    return ""


def _new_write_token(prefix: str) -> str:
    short_prefix = (prefix or "tok")[:8]
    unique = uuid4().hex[:16]
    token = f"{short_prefix}-{unique}"
    if len(token) < 5:
        token = (token + "00000")[:5]
    return token[:32]


def dry_run_item(row: dict[str, Any]) -> dict[str, Any]:
    item = _build_item(row)
    return {
        "ok": True,
        "status": 0,
        "body": "dry-run",
        "preview": item,
        "attachment": {"ok": False, "status": 0, "body": "dry-run"},
        "note": {"ok": False, "status": 0, "body": "dry-run"},
        "parent_key": "",
    }
