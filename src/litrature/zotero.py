from __future__ import annotations

from html import escape, unescape
import json
import os
import re
import unicodedata
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
    creators = _build_mcp_creators(row)

    item = {
        "itemType": "journalArticle",
        "title": title,
        "abstractNote": abstract_note,
        "publicationTitle": journal,
        "date": str(year) if year else "",
        "DOI": doi,
        "url": str(row.get("source_url", "")).strip(),
        "creators": creators,
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
            if not parent_key:
                return {
                    **parent_resp,
                    "attachment": {"ok": False, "status": 0, "body": "未提取到 parent key"},
                    "note": {"ok": False, "status": 0, "body": "未提取到 parent key，无法创建笔记"},
                }

            note = _create_ai_note(
                cfg=cfg,
                parent_key=parent_key,
                row=row,
                timeout_seconds=timeout_seconds,
            )
            return {
                **parent_resp,
                "attachment": {"ok": False, "status": 0, "body": "已按配置禁用 PDF 附件创建"},
                "note": note,
            }
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return {"ok": False, "status": e.code, "body": body}


def _create_item_via_mcp(cfg: ZoteroConfig, row: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    endpoint = os.getenv("ZOTERO_MCP_ENDPOINT", "").strip()
    method = os.getenv("ZOTERO_MCP_METHOD", "zotero.create_item").strip()
    if not endpoint:
        return {"ok": False, "status": 0, "body": "缺少环境变量 ZOTERO_MCP_ENDPOINT"}

    note_html = _build_note_summary(row, timeout_seconds=timeout_seconds)
    request_params = {
        "item": _build_item(row),
        "row": row,
        "attach_pdf": False,
        "local_pdf_path": "",
        "note_html": note_html,
    }

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/event-stream",
    }
    mcp_token = os.getenv("ZOTERO_MCP_TOKEN", "").strip()
    if mcp_token:
        headers["Authorization"] = f"Bearer {mcp_token}"

    mcp_session_id = os.getenv("ZOTERO_MCP_SESSION_ID", "").strip()
    if mcp_session_id:
        # Different MCP servers may use different header names; send common variants.
        headers["Mcp-Session-Id"] = mcp_session_id
        headers["X-Session-Id"] = mcp_session_id

    method_candidates = _build_mcp_method_candidates(method)
    tried_errors: list[str] = []

    for method_name in method_candidates:
        request_payload = {
            "jsonrpc": "2.0",
            "id": "litrature-zotero",
            "method": method_name,
            "params": request_params,
        }

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

        payload = _parse_mcp_payload(text)
        if not isinstance(payload, dict):
            return {"ok": False, "status": 0, "body": f"MCP 返回非 JSON: {text[:500]}"}

        if isinstance(payload, dict) and payload.get("error"):
            err = payload.get("error")
            err_text = json.dumps(err, ensure_ascii=False)
            code = 0
            if isinstance(err, dict):
                try:
                    code = int(err.get("code", 0) or 0)
                except Exception:
                    code = 0
            if code == -32601:
                tried_errors.append(f"{method_name}: {err_text}")
                continue
            return {"ok": False, "status": 0, "body": err_text}

        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, list) and result and isinstance(result[0], dict):
            result = result[0]

        if not isinstance(result, dict):
            return {"ok": False, "status": 0, "body": f"MCP 返回缺少可解析 result: {text[:500]}"}

        return _normalize_mcp_result(result=result, raw_text=text)

    tool_name_candidates = _build_mcp_tool_name_candidates(method_candidates)
    for tool_name in tool_name_candidates:
        tool_resp = _call_mcp_tool(
            endpoint=endpoint,
            headers=headers,
            tool_name=tool_name,
            arguments=request_params,
            timeout_seconds=timeout_seconds,
        )
        if tool_resp.get("ok"):
            return tool_resp
        tried_errors.append(f"tools/call:{tool_name}: {tool_resp.get('body', '')}")

    discovered_tools, list_err = _list_mcp_tools(
        endpoint=endpoint,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    if discovered_tools:
        direct_resp = _try_known_zotero_tools(
            endpoint=endpoint,
            headers=headers,
            discovered_tools=discovered_tools,
            row=row,
            note_html=note_html,
            timeout_seconds=timeout_seconds,
        )
        if direct_resp.get("ok"):
            return direct_resp
        if direct_resp.get("body"):
            tried_errors.append(f"known-tools: {direct_resp.get('body', '')}")

        for tool_name in _rank_mcp_tool_candidates(discovered_tools, method_candidates):
            tool_resp = _call_mcp_tool(
                endpoint=endpoint,
                headers=headers,
                tool_name=tool_name,
                arguments=request_params,
                timeout_seconds=timeout_seconds,
            )
            if tool_resp.get("ok"):
                return tool_resp
            tried_errors.append(f"tools/call:{tool_name}: {tool_resp.get('body', '')}")
    elif list_err:
        tried_errors.append(f"tools/list: {list_err}")

    return {
        "ok": False,
        "status": 0,
        "body": "MCP 方法未命中。已尝试: " + " | ".join(tried_errors),
    }


def _build_mcp_method_candidates(method: str) -> list[str]:
    base = method.strip() or "zotero.create_item"
    candidates: list[str] = []
    if base.lower() != "auto":
        candidates.append(base)

    if "." in base:
        namespace, action = base.rsplit(".", 1)
        if "_" in action:
            parts = [p for p in action.split("_") if p]
            if parts:
                camel = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
                candidates.append(f"{namespace}.{camel}")
    else:
        if "_" in base:
            parts = [p for p in base.split("_") if p]
            if parts:
                camel = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
                candidates.append(camel)

    candidates.extend([
        "zotero.create_item",
        "zotero.createItem",
        "create_item",
        "createItem",
    ])

    uniq: list[str] = []
    seen: set[str] = set()
    for m in candidates:
        m2 = str(m).strip()
        if not m2 or m2 in seen:
            continue
        seen.add(m2)
        uniq.append(m2)
    return uniq


def _build_mcp_tool_name_candidates(method_candidates: list[str]) -> list[str]:
    candidates = [
        "zotero.create_item",
        "zotero.createItem",
        "zotero_create_item",
        "zotero-create-item",
        "create_item",
        "createItem",
    ]
    for m in method_candidates:
        m2 = str(m).strip()
        if not m2:
            continue
        candidates.append(m2)
        candidates.append(m2.replace(".", "_"))
        candidates.append(m2.replace(".", "-"))

    uniq: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        n = str(name).strip()
        if not n or n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq


def _call_mcp_tool(
    endpoint: str,
    headers: dict[str, str],
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    safe_arguments = _sanitize_mcp_value(arguments)
    payload = {
        "jsonrpc": "2.0",
        "id": "litrature-zotero-tool",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": safe_arguments,
        },
    }

    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
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

    data = _parse_mcp_payload(text)
    if not isinstance(data, dict):
        return {"ok": False, "status": 0, "body": f"MCP 返回非 JSON: {text[:500]}"}

    if isinstance(data, dict) and data.get("error"):
        return {"ok": False, "status": 0, "body": json.dumps(data.get("error"), ensure_ascii=False)}

    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        return {"ok": False, "status": 0, "body": f"tools/call 返回缺少 result: {text[:500]}"}

    if bool(result.get("isError", False)):
        return {"ok": False, "status": 0, "body": json.dumps(result, ensure_ascii=False)[:500]}

    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return _normalize_mcp_result(result=structured, raw_text=text)

    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            txt = str(block.get("text", "")).strip()
            if not txt:
                continue
            try:
                parsed = json.loads(txt)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return _normalize_mcp_result(result=parsed, raw_text=text)

    return {"ok": False, "status": 0, "body": f"tools/call 未返回可解析结构: {text[:500]}"}


def _sanitize_mcp_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_mcp_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_mcp_value(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_mcp_value(v) for v in value]
    if isinstance(value, str):
        txt = unicodedata.normalize("NFKC", value)
        txt = txt.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-").replace("\u2013", "-")
        txt = txt.replace("\u2014", "-").replace("\u2212", "-")
        # Remove control chars that can break some non-standard JSON parsers.
        txt = "".join(ch for ch in txt if (ch == "\n" or ch == "\r" or ch == "\t" or ord(ch) >= 32))
        return txt
    return value


def _list_mcp_tools(endpoint: str, headers: dict[str, str], timeout_seconds: int) -> tuple[list[str], str]:
    methods = ["tools/list", "tools.list", "mcp/tools/list"]
    params_variants: list[dict[str, Any] | None] = [{}, {"cursor": ""}, None]
    errors: list[str] = []

    for method_name in methods:
        for params in params_variants:
            payload: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": "litrature-zotero-tools-list",
                "method": method_name,
            }
            if params is not None:
                payload["params"] = params

            req = Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers=headers,
            )

            try:
                with urlopen(req, timeout=timeout_seconds) as resp:
                    text = resp.read().decode("utf-8")
            except HTTPError as e:
                errors.append(f"{method_name}: HTTP {e.code}")
                continue
            except Exception as e:
                errors.append(f"{method_name}: {e}")
                continue

            data = _parse_mcp_payload(text)
            if not isinstance(data, dict):
                errors.append(f"{method_name}: non-json")
                continue

            if data.get("error"):
                err = data.get("error")
                try:
                    err_code = int((err or {}).get("code", 0)) if isinstance(err, dict) else 0
                except Exception:
                    err_code = 0
                if err_code == -32601:
                    errors.append(f"{method_name}: method not found")
                    continue
                errors.append(f"{method_name}: {json.dumps(err, ensure_ascii=False)[:200]}")
                continue

            result = data.get("result")
            names = _extract_mcp_tool_names(result)
            if names:
                return names, ""

    return [], " | ".join(errors)[:500]


def _extract_mcp_tool_names(result: Any) -> list[str]:
    tools: Any = None
    if isinstance(result, dict):
        tools = result.get("tools")
        if tools is None:
            tools = result.get("items")
        if tools is None:
            tools = result.get("data")
    elif isinstance(result, list):
        tools = result

    names: list[str] = []
    if isinstance(tools, list):
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or item.get("tool", "") or item.get("id", "")).strip()
            if name:
                names.append(name)
    elif isinstance(tools, dict):
        for key, value in tools.items():
            key_name = str(key).strip()
            if key_name:
                names.append(key_name)
            if isinstance(value, dict):
                vname = str(value.get("name", "") or value.get("id", "")).strip()
                if vname:
                    names.append(vname)

    uniq: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        uniq.append(name)
    return uniq


def _rank_mcp_tool_candidates(discovered: list[str], method_candidates: list[str]) -> list[str]:
    discovered_clean = [str(x).strip() for x in discovered if str(x).strip()]
    priority: list[str] = []

    seed = _build_mcp_tool_name_candidates(method_candidates)
    seed_lower = {s.lower() for s in seed}
    for name in discovered_clean:
        if name.lower() in seed_lower:
            priority.append(name)

    for name in discovered_clean:
        lower = name.lower()
        if "zotero" in lower and any(k in lower for k in ("create", "add", "import", "item", "paper", "article")):
            priority.append(name)

    for name in discovered_clean:
        lower = name.lower()
        if any(k in lower for k in ("create", "add", "import", "item", "paper", "article")):
            priority.append(name)

    for name in discovered_clean:
        priority.append(name)

    uniq: list[str] = []
    seen: set[str] = set()
    for name in priority:
        if name in seen:
            continue
        seen.add(name)
        uniq.append(name)
    return uniq


def _try_known_zotero_tools(
    endpoint: str,
    headers: dict[str, str],
    discovered_tools: list[str],
    row: dict[str, Any],
    note_html: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    discovered = {str(x).strip().lower() for x in discovered_tools if str(x).strip()}

    # This Zotero MCP plugin exposes write_item/write_note, not create_item.
    write_item_name = ""
    for candidate in ("write_item", "write-item", "writeItem"):
        if candidate.lower() in discovered:
            write_item_name = candidate
            break

    if not write_item_name:
        return {"ok": False, "status": 0, "body": "未发现 write_item 工具"}

    item = _build_item(row)
    fields = {
        "title": str(item.get("title", "")).strip(),
        "abstractNote": str(item.get("abstractNote", "")).strip(),
        "publicationTitle": str(item.get("publicationTitle", "")).strip(),
        "date": str(item.get("date", "")).strip(),
        "DOI": str(item.get("DOI", "")).strip(),
        "url": str(item.get("url", "")).strip(),
    }
    fields = {k: v for k, v in fields.items() if v}
    creators = _build_mcp_creators(row)

    create_args: dict[str, Any] = {
        "action": "create",
        "itemType": "journalArticle",
        "fields": fields,
        "creators": creators,
        "tags": ["auto-import"],
    }
    write_item_resp = _call_mcp_tool(
        endpoint=endpoint,
        headers=headers,
        tool_name=write_item_name,
        arguments=create_args,
        timeout_seconds=timeout_seconds,
    )
    if not write_item_resp.get("ok"):
        return write_item_resp

    parent_key = str(write_item_resp.get("parent_key", "")).strip()
    if not parent_key:
        parent_key = _extract_mcp_parent_key(str(write_item_resp.get("body", "")))

    note_resp = {"ok": False, "status": 0, "body": "未执行"}
    write_note_name = ""
    for candidate in ("write_note", "write-note", "writeNote"):
        if candidate.lower() in discovered:
            write_note_name = candidate
            break

    if write_note_name:
        note_markdown = _build_note_markdown_for_mcp(row=row, timeout_seconds=timeout_seconds)
        note_args = {
            "action": "create",
            "content": note_markdown,
            "tags": ["auto-import"],
        }
        if parent_key:
            note_args["parentKey"] = parent_key
        note_resp = _call_mcp_tool(
            endpoint=endpoint,
            headers=headers,
            tool_name=write_note_name,
            arguments=note_args,
            timeout_seconds=timeout_seconds,
        )

        # Fallback: some servers accept HTML better than Markdown.
        if (not bool(note_resp.get("ok", False))) and note_html:
            note_args_html = {
                "action": "create",
                "content": note_html,
                "tags": ["auto-import"],
            }
            if parent_key:
                note_args_html["parentKey"] = parent_key
            note_resp = _call_mcp_tool(
                endpoint=endpoint,
                headers=headers,
                tool_name=write_note_name,
                arguments=note_args_html,
                timeout_seconds=timeout_seconds,
            )

    return {
        "ok": True,
        "status": int(write_item_resp.get("status", 200) or 200),
        "body": str(write_item_resp.get("body", "")),
        "parent_key": parent_key,
        "attachment": {"ok": False, "status": 0, "body": "当前插件未通过 write_item 直接处理附件"},
        "note": {
            "ok": bool(note_resp.get("ok", False)),
            "status": int(note_resp.get("status", 0) or 0),
            "body": str(note_resp.get("body", "")),
        },
    }


def _build_mcp_creators(row: dict[str, Any]) -> list[dict[str, str]]:
    # Zotero MCP write_item may require at least one creator.
    raw_authors: Any = row.get("authors")
    if raw_authors is None:
        raw_authors = row.get("author")

    names: list[str] = []
    if isinstance(raw_authors, list):
        for item in raw_authors:
            if isinstance(item, str):
                n = item.strip()
                if n:
                    names.append(n)
            elif isinstance(item, dict):
                given = str(item.get("given", "")).strip()
                family = str(item.get("family", "")).strip()
                name = str(item.get("name", "")).strip()
                if given or family:
                    n = f"{given} {family}".strip()
                    if n:
                        names.append(n)
                elif name:
                    names.append(name)
    elif isinstance(raw_authors, str):
        n = raw_authors.strip()
        if n:
            names.append(n)

    creators: list[dict[str, str]] = []
    for name in names:
        creator = _name_to_creator(name)
        if creator:
            creators.append(creator)

    if creators:
        return creators

    # Fallback to avoid hard failure when source metadata has no author field.
    return [{"creatorType": "author", "lastName": "Unknown"}]


def _name_to_creator(name: str) -> dict[str, str] | None:
    n = str(name or "").strip()
    if not n:
        return None

    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return {"creatorType": "author", "firstName": parts[1], "lastName": parts[0]}

    chunks = [c for c in n.split() if c]
    if len(chunks) == 1:
        return {"creatorType": "author", "lastName": chunks[0]}

    return {
        "creatorType": "author",
        "firstName": " ".join(chunks[:-1]),
        "lastName": chunks[-1],
    }


def _parse_mcp_payload(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    # Standard JSON-RPC response.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Some MCP servers stream Server-Sent Events (text/event-stream).
    sse_data: list[str] = []
    for line in raw.splitlines():
        ln = line.strip()
        if not ln.startswith("data:"):
            continue
        chunk = ln[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        sse_data.append(chunk)

    for chunk in reversed(sse_data):
        try:
            parsed = json.loads(chunk)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed

    # Fallback for line-delimited JSON output.
    for line in reversed(raw.splitlines()):
        ln = line.strip()
        if not ln or ln.startswith("event:") or ln.startswith("id:"):
            continue
        try:
            parsed = json.loads(ln)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _normalize_mcp_result(result: dict[str, Any], raw_text: str) -> dict[str, Any]:
    status = _safe_int(result.get("status", result.get("statusCode", 200)), 200)
    parent_key = str(
        result.get("parent_key", "")
        or result.get("itemKey", "")
        or result.get("key", "")
        or (result.get("item", {}) or {}).get("key", "")
        or (result.get("data", {}) or {}).get("key", "")
        or (result.get("result", {}) or {}).get("key", "")
    ).strip()
    if not parent_key:
        parent_key = _extract_mcp_parent_key(raw_text)

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

    explicit_ok = result.get("ok")
    has_parent = bool(parent_key)
    if isinstance(explicit_ok, bool):
        top_ok = explicit_ok
    else:
        # Some MCP servers do not return a unified success flag or item key field.
        # For compatibility, treat HTTP-style success as success unless explicit error is present.
        has_explicit_error = bool(result.get("error") or result.get("errors") or result.get("isError", False))
        top_ok = status < 400 and not has_explicit_error

    if not top_ok and status < 400 and not has_parent:
        status = 0

    return {
        "ok": top_ok,
        "status": status,
        "body": raw_text,
        "parent_key": parent_key,
        "attachment": attachment,
        "note": note,
    }


def _extract_mcp_parent_key(text: str) -> str:
    # Try API-style payload first.
    key = extract_success_key(text)
    if key:
        return key

    # Fallback: scan for Zotero-like 8-char item keys in generic MCP text blocks.
    match = re.search(r'"key"\s*:\s*"([A-Z0-9]{8})"', text)
    if match:
        return str(match.group(1)).strip()
    return ""


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


def _build_note_markdown_for_mcp(row: dict[str, Any], timeout_seconds: int) -> str:
    try:
        from .summarizer import generate_note_markdown

        md = generate_note_markdown(row, timeout_seconds=min(timeout_seconds, 20))
        if md and str(md).strip():
            return str(md).strip()
    except Exception:
        pass

    title = str(row.get("title", "")).strip() or "Untitled"
    doi = str(row.get("doi", "")).strip()
    source_url = str(row.get("source_url", "")).strip()
    journal = str(row.get("journal", "")).strip()
    year = str(row.get("year", "")).strip()
    authors = row.get("authors")
    if isinstance(authors, list):
        author_text = "; ".join(str(a).strip() for a in authors if str(a).strip())
    else:
        author_text = str(authors or "").strip()
    if not author_text:
        author_text = "Unknown"
    abstract = str(row.get("abstract", "")).strip()
    if len(abstract) > 2000:
        abstract = abstract[:2000]
    return (
        f"# {title}\n\n"
        f"- Title: {title}\n"
        f"- Authors: {author_text}\n"
        f"- Year: {year}\n"
        f"- Journal: {journal}\n"
        f"- DOI: {doi}\n"
        f"- URL: {source_url}\n\n"
        "## 摘要\n"
        f"{abstract if abstract else '无摘要'}\n"
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
