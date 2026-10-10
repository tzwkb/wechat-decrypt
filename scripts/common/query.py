#!/usr/bin/env python3
"""wechat-decrypt 命令行查询入口（唯一 entry；MCP server 为可选薄层,内部调这里）。

子命令(统一 --json 可输出结构化):
  list                        列出所有会话
  read <contact> [-n N -d D]  读与某人的聊天
  search <kw> [-d D -n N]     全文搜索
  recent [-d D -n N]          最近动态
  summary [-d D]              结构化摘要(待办分析)
  events [-e EVENT -d D -n N] 系统事件（拍一拍/撤回/群事件等）

用法: python query.py <子命令> [参数] [--json]
"""
import sys
import os
import time
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # skill 根
import config  # noqa: E402
import appmsg  # noqa: E402
import contacts  # noqa: E402
import db  # noqa: E402
import message  # noqa: E402


def _msg_dbs_tables():
    for db_path in db.get_message_dbs():
        tabs = {t.strip() for t in db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")}
        yield db_path, tabs


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _chunks(values: list[str], size: int = 200):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _iter_query_pages(db_path: str, selects: list[str], page_size: int = 500):
    union = " UNION ALL ".join(selects)
    offset = 0
    while True:
        rows = db.query(
            db_path,
            "SELECT * FROM (" + union + ") "
            "ORDER BY create_time DESC, source_table ASC, local_id DESC, server_id DESC "
            f"LIMIT {page_size} OFFSET {offset};",
        )
        yield from rows
        if len(rows) < page_size:
            return
        offset += page_size


def _search_identity(db_path: str, row: dict) -> tuple:
    return (
        db_path,
        row.get("source_table", ""),
        row.get("local_id"),
        row.get("server_id"),
        row.get("create_time"),
    )


def list_chats() -> list[dict]:
    name2id = db.get_name2id()
    return [{"wxid": wxid, "display": contacts.resolve_contact_name(wxid)}
            for _table, wxid in sorted(name2id.items(), key=lambda x: x[1])]


def read_chat(contact: str, limit: int = 50, days: int = 7) -> dict:
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    matched = contacts.find_contact(contact, name2id)
    if not matched:
        return {"error": f"未找到匹配 '{contact}' 的联系人", "candidates": []}
    if len(matched) > 5:
        return {"error": f"匹配 '{contact}' 的联系人太多({len(matched)})",
                "candidates": [{"wxid": w, "display": d} for _t, w, d in matched[:10]]}
    out = []
    for table, wxid, display in matched:
        msgs = []
        for db_path, tabs in _msg_dbs_tables():
            if table not in tabs:
                continue
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, "
                f"hex(message_content) AS message_hex "
                f"FROM {table} WHERE create_time > {since} ORDER BY create_time DESC LIMIT {limit};")
            msgs.extend(_fmt_msg(row) for row in rows)
        newest = sorted(msgs, key=lambda x: x["_ts"], reverse=True)[:limit]
        out.append({"wxid": wxid, "display": display,
                    "messages": sorted(newest, key=lambda x: x["_ts"])})
    return {"chats": out}


def search(keyword: str, days: int = 30, limit: int = 50) -> dict:
    name2id = db.get_name2id()
    scan_until = int(time.time())
    since = scan_until - days * 86400
    kw = keyword.replace("'", "''")
    kw_hex = keyword.encode("utf-8").hex().upper()
    keyword_folded = keyword.casefold()
    hits = []
    seen = set()

    def append_if_match(db_path: str, row: dict) -> bool:
        identity = _search_identity(db_path, row)
        if identity in seen:
            return False
        if keyword_folded not in _searchable_text(row).casefold():
            return False
        seen.add(identity)
        table = row.get("source_table", "")
        formatted = _fmt_msg(row)
        formatted["contact"] = contacts.resolve_contact_name(name2id.get(table, table))
        hits.append(formatted)
        return True

    for db_path, tabs in _msg_dbs_tables():
        tables = sorted(t for t in tabs if t.startswith("Msg_"))
        for table_batch in _chunks(tables):
            selects = []
            fallback_selects = []
            for table in table_batch:
                source = table.replace("'", "''")
                selects.append(
                    f"SELECT '{source}' AS source_table, local_id, server_id, "
                    f"create_time, local_type, "
                    f"real_sender_id, hex(message_content) AS message_hex "
                    f"FROM {_quoted_identifier(table)} WHERE create_time > {since} "
                    f"AND create_time <= {scan_until} "
                    f"AND (message_content LIKE '%{kw}%' "
                    f"OR instr(hex(message_content), '{kw_hex}') > 0)"
                )
                fallback_selects.append(
                    f"SELECT '{source}' AS source_table, local_id, server_id, "
                    f"create_time, local_type, "
                    f"real_sender_id, hex(message_content) AS message_hex "
                    f"FROM {_quoted_identifier(table)} WHERE create_time > {since} "
                    f"AND create_time <= {scan_until} "
                    "AND (((CAST(local_type AS INTEGER) & 65535) = 49) "
                    "OR hex(substr(message_content, 1, 4)) = '28B52FFD')"
                )
            if not selects:
                continue
            matched_rows = db.query(
                db_path,
                "SELECT * FROM (" + " UNION ALL ".join(selects) + ") "
                f"ORDER BY create_time DESC LIMIT {limit};",
            )
            for row in matched_rows:
                append_if_match(db_path, row)

            fallback_matches = 0
            for row in _iter_query_pages(db_path, fallback_selects):
                if append_if_match(db_path, row):
                    fallback_matches += 1
                    if fallback_matches >= limit:
                        break
    hits.sort(key=lambda x: x["_ts"], reverse=True)
    hits = hits[:limit]
    return {"keyword": keyword, "count": len(hits), "messages": hits}


def recent(days: int = 3, limit: int = 100) -> dict:
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    messages = []
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, "
                f"hex(message_content) AS message_hex FROM {table} "
                f"WHERE create_time > {since} ORDER BY create_time DESC LIMIT {limit};")
            if not rows:
                continue
            wxid = name2id.get(table, table)
            messages.extend((table, wxid, _fmt_msg(r)) for r in rows)
    messages.sort(key=lambda x: x[2]["_ts"], reverse=True)
    messages = messages[:limit]
    by_contact: dict[str, dict] = {}
    for table, wxid, formatted in messages:
        conv = by_contact.setdefault(
            table,
            {"wxid": wxid, "display": contacts.resolve_contact_name(wxid), "messages": []},
        )
        conv["messages"].append(formatted)
    convs = []
    for conv in by_contact.values():
        conv["count"] = len(conv["messages"])
        convs.append(conv)
    convs.sort(key=lambda c: c["messages"][0]["_ts"], reverse=True)
    return {"days": days, "total": len(messages), "conversations": convs}


def summary(days: int = 3) -> dict:
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    by_contact: dict[str, dict] = {}
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, "
                f"hex(message_content) AS message_hex FROM {table} "
                f"WHERE create_time > {since} "
                f"AND ((CAST(local_type AS INTEGER) & 65535) IN (1, 49, 10000, 10002)) "
                f"ORDER BY create_time DESC LIMIT 30;")
            text = [m for m in (_fmt_msg(r) for r in rows) if m["is_text"]]
            if text:
                wxid = name2id.get(table, table)
                conv = by_contact.setdefault(
                    table,
                    {"wxid": wxid, "display": contacts.resolve_contact_name(wxid), "messages": []},
                )
                conv["messages"].extend(text)
    convs = list(by_contact.values())
    for conv in convs:
        conv["messages"] = sorted(conv["messages"], key=lambda x: x["_ts"])[-20:]
    convs.sort(key=lambda c: max(m["_ts"] for m in c["messages"]), reverse=True)
    return {"days": days, "today": datetime.now().strftime("%Y-%m-%d %A"), "conversations": convs}


def system_events(event: str = "", days: int = 30, limit: int = 100) -> dict:
    from collections import Counter

    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    target = message.normalize_system_event_filter(event)
    strict_event = target in message.SYSTEM_EVENTS
    events = []
    for db_path, tabs in _msg_dbs_tables():
        tables = sorted(t for t in tabs if t.startswith("Msg_"))
        for table_batch in _chunks(tables):
            selects = []
            for table in table_batch:
                source = table.replace("'", "''")
                selects.append(
                    f"SELECT '{source}' AS source_table, create_time, local_type, "
                    f"real_sender_id, hex(message_content) AS message_hex "
                    f"FROM {_quoted_identifier(table)} "
                    f"WHERE create_time > {since} "
                    f"AND ((CAST(local_type AS INTEGER) & 65535) IN (10000, 10002))"
                )
            if not selects:
                continue
            row_limit = "" if target else f"LIMIT {limit}"
            rows = db.query(
                db_path,
                "SELECT * FROM (" + " UNION ALL ".join(selects) + ") "
                f"ORDER BY create_time DESC {row_limit};",
            )
            for row in rows:
                table = row.get("source_table", "")
                wxid = name2id.get(table, table)
                formatted = _fmt_msg(row)
                if (
                    target
                    and (
                        formatted["event"] != target
                        if strict_event
                        else target not in formatted["type"].lower()
                        and target not in formatted["content"].lower()
                    )
                ):
                    continue
                formatted["contact"] = contacts.resolve_contact_name(wxid)
                formatted["wxid"] = wxid
                events.append(formatted)
    events.sort(key=lambda item: item["_ts"], reverse=True)
    events = events[:limit]
    counts = Counter(item["event"] for item in events)
    return {
        "days": days,
        "filter": target,
        "count": len(events),
        "by_event": dict(counts),
        "events": events,
    }


def stats(days: int = 30) -> dict:
    from collections import Counter
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    by_contact = Counter()
    by_type = Counter()
    by_day = Counter()
    unknown_app_types = Counter()
    total = 0
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, hex(message_content) AS message_hex "
                f"FROM {table} "
                f"WHERE create_time > {since};",
            )
            disp = contacts.resolve_contact_name(name2id.get(table, table))
            for r in rows:
                total += 1
                by_contact[disp] += 1
                type_key = message.normalize_type(r.get("local_type", ""))
                if type_key in ("10000", "10002"):
                    content = _row_content(r)
                    type_label = message.parse_system_message(
                        content,
                        default_event="recall" if type_key == "10002" else "",
                    )["label"]
                elif type_key == "49":
                    parsed_app = appmsg.parse_app_message(
                        _row_content(r), r.get("local_type", "")
                    )
                    type_label = parsed_app["label"]
                    if parsed_app["app_type"] not in appmsg.APP_MESSAGE_TYPES:
                        unknown_app_types[parsed_app["app_type"]] += 1
                else:
                    type_label = message.MSG_TYPES.get(type_key, "其他")
                by_type[type_label] += 1
                ts = int(r.get("create_time", "0") or "0")
                if ts:
                    by_day[datetime.fromtimestamp(ts).strftime("%Y-%m-%d")] += 1
    return {
        "days": days,
        "total": total,
        "by_contact": by_contact.most_common(15),
        "by_type": by_type.most_common(),
        "by_day": sorted(by_day.items()),
        "unknown_app_types": [
            {"app_type": app_type, "count": count}
            for app_type, count in unknown_app_types.most_common()
        ],
    }


def media(out: str = "") -> dict:
    import export_media
    base = db.get_account_files_dir()
    out = out or os.path.expanduser("~/Desktop/wechat_media")
    return {"out": out, **export_media.export(base, out)}


def openfile(name: str, limit: int = 8000) -> dict:
    import glob as _g
    import read_doc
    base = db.get_account_files_dir()
    matches = [m for m in _g.glob(os.path.join(base, "msg", "file", "**", f"*{name}*"), recursive=True) if os.path.isfile(m)]
    if not matches:
        return {"error": f"未在 msg/file 找到含 '{name}' 的文档"}
    return {"path": matches[0], "matches": len(matches), "content": read_doc.read_file(matches[0], limit)}


def _decode_content(mc) -> str:
    return message.decode_message_content(mc)


def _row_content(row: dict) -> str:
    encoded = row.get("message_hex")
    if encoded is not None:
        try:
            return _decode_content(bytes.fromhex(str(encoded)))
        except ValueError:
            return ""
    return _decode_content(row.get("message_content"))


def _searchable_text(row: dict) -> str:
    type_key = message.normalize_type(row.get("local_type", ""))
    content = _row_content(row)
    if type_key in ("10000", "10002"):
        system = message.parse_system_message(
            content,
            default_event="recall" if type_key == "10002" else "",
        )
        return " ".join((system["label"], system["event"], system["text"], content))
    if type_key == "49":
        parsed = appmsg.parse_app_message(content, row.get("local_type", ""))
        return " ".join(
            [content, *(str(value) for value in parsed.values() if value is not None)]
        )
    return " ".join((message.MSG_TYPES.get(type_key, "其他"), content))


def _fmt_msg(row: dict) -> dict:
    ts = row.get("create_time", "0")
    try:
        ts_int = int(ts or "0")
    except (TypeError, ValueError):
        ts_int = 0
    type_key = message.normalize_type(row.get("local_type", ""))
    content = _row_content(row)
    if type_key in ("10000", "10002"):
        system = message.parse_system_message(
            content,
            default_event="recall" if type_key == "10002" else "",
        )
        return {
            "time": message.format_time(ts),
            "_ts": ts_int,
            "direction": f"[系统·{system['label']}]",
            "type": system["label"],
            "event": system["event"],
            "content": system["text"][:500].replace("\n", " "),
            "is_text": bool(system["text"]),
            "is_system": True,
        }
    is_me = message.is_my_message(row.get("real_sender_id", ""))
    if type_key == "49":
        app = appmsg.parse_app_message(content, row.get("local_type", ""))
        details = app["summary"].replace("\n", " ")[:500]
        display = f"[{app['label']}]" + (f" {details}" if details else "")
        return {
            "time": message.format_time(ts),
            "_ts": ts_int,
            "direction": "[我]" if is_me else "[对方]",
            "type": app["label"],
            "event": None,
            "content": display,
            "is_text": True,
            "is_system": False,
            "app": app,
        }
    is_text = type_key == "1" and not content.startswith("<")
    return {
        "time": message.format_time(ts), "_ts": ts_int,
        "direction": "[我]" if is_me else "[对方]",
        "type": message.MSG_TYPES.get(type_key, "其他"),
        "event": None,
        "content": content[:500].replace("\n", " ") if is_text else "",
        "is_text": is_text,
        "is_system": False,
    }


# ── 人类可读渲染(非 --json 时) ─────────────────────────────────
def _human(cmd: str, r) -> str:
    if isinstance(r, dict) and r.get("error"):
        return r["error"] + ("\n" + "\n".join(f"  {c['display']} (wxid: {c['wxid']})" for c in r.get("candidates", [])) if r.get("candidates") else "")
    if cmd == "list":
        return f"共 {len(r)} 个对话:\n" + "\n".join(f"  {c['display']} (wxid: {c['wxid']})" for c in r)
    if cmd == "read":
        out = []
        for chat in r["chats"]:
            out.append(f"\n=== 与 {chat['display']} 的对话 ===")
            for m in chat["messages"]:
                out.append(f"  [{m['time']}] {m['direction']} " + (m["content"] if m["is_text"] else f"[{m['type']}]"))
        return "\n".join(out) or "未找到消息"
    if cmd == "search":
        out = [f"搜索 '{r['keyword']}' 找到 {r['count']} 条:\n"]
        for m in r["messages"]:
            out.append(f"  [{m['time']}] {m.get('contact','')} {m['direction']}: " + (m["content"] if m["is_text"] else f"[{m['type']}]"))
        return "\n".join(out)
    if cmd == "recent":
        out = [f"最近 {r['days']} 天共 {r['total']} 条,涉及 {len(r['conversations'])} 个对话:\n"]
        for c in r["conversations"]:
            out.append(f"\n--- {c['display']} ({c['count']} 条) ---")
            for m in c["messages"][:20]:
                if m["is_text"] or m["type"] in ("图片", "语音", "视频", "链接"):
                    out.append(f"  [{m['time']}] {m['direction']} " + (m["content"] if m["is_text"] else f"[{m['type']}]"))
        return "\n".join(out)
    if cmd == "summary":
        out = [f"=== 微信聊天摘要(最近 {r['days']} 天)===", f"今天 {r['today']}",
               f"涉及 {len(r['conversations'])} 个对话\n[我]=用户发, [对方]=联系人发\n分析: 待办/承诺/计划/待回复\n"]
        for c in r["conversations"]:
            out.append(f"\n--- {c['display']} ---")
            for m in c["messages"]:
                out.append(f"  [{m['time']}] {m['direction']} {m['content']}")
        return "\n".join(out)
    if cmd == "events":
        label = f"，筛选 {r['filter']}" if r["filter"] else ""
        out = [f"最近 {r['days']} 天系统事件 {r['count']} 条{label}:"]
        for item in r["events"]:
            content = f" {item['content']}" if item["content"] else ""
            out.append(
                f"  [{item['time']}] {item['contact']} {item['direction']}{content}"
            )
        return "\n".join(out)
    if cmd == "stats":
        out = [f"=== 统计(最近 {r['days']} 天, 共 {r['total']} 条) ===", "\n发言排行:"]
        out += [f"  {n:>5}  {c}" for c, n in r["by_contact"]]
        out.append("\n类型分布:")
        out += [f"  {n:>5}  {t}" for t, n in r["by_type"]]
        if r.get("unknown_app_types"):
            out.append("\n未识别分享子类型:")
            out += [
                f"  {item['count']:>5}  app_type={item['app_type']}"
                for item in r["unknown_app_types"]
            ]
        return "\n".join(out)
    if cmd == "media":
        return f"导出 → {r['out']}: {r['docs']} 文档, {r['videos']} 视频, {r['images']} 图片(跳过 {r['enc_dat']} 个 .dat 加密原图)"
    if cmd == "openfile":
        return r["error"] if r.get("error") else f"文档: {r['path']}(匹配 {r['matches']} 个)\n\n{r['content']}"
    return json.dumps(r, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="wechat-decrypt 命令行查询")
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", parents=[base])
    p = sub.add_parser("read", parents=[base]); p.add_argument("contact"); p.add_argument("-n", "--limit", type=int, default=50); p.add_argument("-d", "--days", type=int, default=7)
    p = sub.add_parser("search", parents=[base]); p.add_argument("keyword"); p.add_argument("-d", "--days", type=int, default=30); p.add_argument("-n", "--limit", type=int, default=50)
    p = sub.add_parser("recent", parents=[base]); p.add_argument("-d", "--days", type=int, default=3); p.add_argument("-n", "--limit", type=int, default=100)
    p = sub.add_parser("summary", parents=[base]); p.add_argument("-d", "--days", type=int, default=3)
    p = sub.add_parser("events", parents=[base]); p.add_argument("-e", "--event", default=""); p.add_argument("-d", "--days", type=int, default=30); p.add_argument("-n", "--limit", type=int, default=100)
    p = sub.add_parser("stats", parents=[base]); p.add_argument("-d", "--days", type=int, default=30)
    p = sub.add_parser("media", parents=[base]); p.add_argument("-o", "--out", default="")
    p = sub.add_parser("openfile", parents=[base]); p.add_argument("name")
    a = ap.parse_args()
    if a.cmd == "list":
        r = list_chats()
    elif a.cmd == "read":
        r = read_chat(a.contact, a.limit, a.days)
    elif a.cmd == "search":
        r = search(a.keyword, a.days, a.limit)
    elif a.cmd == "recent":
        r = recent(a.days, a.limit)
    elif a.cmd == "summary":
        r = summary(a.days)
    elif a.cmd == "events":
        r = system_events(a.event, a.days, a.limit)
    elif a.cmd == "stats":
        r = stats(a.days)
    elif a.cmd == "media":
        r = media(a.out)
    elif a.cmd == "openfile":
        r = openfile(a.name)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else _human(a.cmd, r))


if __name__ == "__main__":
    main()
