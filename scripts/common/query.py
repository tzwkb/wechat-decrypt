#!/usr/bin/env python3
"""wechat-decrypt 命令行查询入口（唯一 entry；MCP server 为可选薄层,内部调这里）。

子命令(统一 --json 可输出结构化):
  list                        列出所有会话
  read <contact> [-n N -d D]  读与某人的聊天
  search <kw> [-d D -n N]     全文搜索
  recent [-d D -n N]          最近动态
  summary [-d D]              结构化摘要(待办分析)

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
import contacts  # noqa: E402
import db  # noqa: E402
import message  # noqa: E402


def _msg_dbs_tables():
    for db_path in db.get_message_dbs():
        tabs = {t.strip() for t in db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")}
        yield db_path, tabs


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
                f"SELECT create_time, local_type, real_sender_id, message_content "
                f"FROM {table} WHERE create_time > {since} ORDER BY create_time DESC LIMIT {limit};")
            for row in reversed(rows):
                msgs.append(_fmt_msg(row))
        out.append({"wxid": wxid, "display": display, "messages": msgs})
    return {"chats": out}


def search(keyword: str, days: int = 30, limit: int = 50) -> dict:
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    kw = keyword.replace("'", "''")
    hits = []
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, message_content FROM {table} "
                f"WHERE create_time > {since} AND message_content LIKE '%{kw}%' "
                f"ORDER BY create_time DESC LIMIT {limit};")
            for row in rows:
                m = _fmt_msg(row)
                m["contact"] = contacts.resolve_contact_name(name2id.get(table, table))
                hits.append(m)
    hits.sort(key=lambda x: x["_ts"], reverse=True)
    return {"keyword": keyword, "count": len(hits), "messages": hits[:limit]}


def recent(days: int = 3, limit: int = 100) -> dict:
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    by_contact: dict[str, list] = {}
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, message_content FROM {table} "
                f"WHERE create_time > {since} ORDER BY create_time DESC LIMIT {limit};")
            if not rows:
                continue
            disp = contacts.resolve_contact_name(name2id.get(table, table))
            by_contact.setdefault(disp, []).extend(_fmt_msg(r) for r in rows)
    total = sum(len(v) for v in by_contact.values())
    convs = [{"display": k, "count": len(v),
              "messages": sorted(v, key=lambda x: x["_ts"], reverse=True)[:20]}
             for k, v in sorted(by_contact.items(), key=lambda x: -len(x[1]))]
    return {"days": days, "total": total, "conversations": convs}


def summary(days: int = 3) -> dict:
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    convs = []
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, message_content FROM {table} "
                f"WHERE create_time > {since} AND local_type = '1' ORDER BY create_time DESC LIMIT 30;")
            text = [_fmt_msg(r) for r in rows
                    if r.get("message_content") and not r["message_content"].startswith("<")]
            if text:
                convs.append({"display": contacts.resolve_contact_name(name2id.get(table, table)),
                              "messages": sorted(text, key=lambda x: x["_ts"])[-20:]})
    convs.sort(key=lambda c: max(m["_ts"] for m in c["messages"]), reverse=True)
    return {"days": days, "today": datetime.now().strftime("%Y-%m-%d %A"), "conversations": convs}


def stats(days: int = 30) -> dict:
    from collections import Counter
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    by_contact, by_type, by_day = Counter(), Counter(), Counter()
    total = 0
    for db_path, tabs in _msg_dbs_tables():
        for table in (t for t in tabs if t.startswith("Msg_")):
            rows = db.query(db_path, f"SELECT create_time, local_type FROM {table} WHERE create_time > {since};")
            disp = contacts.resolve_contact_name(name2id.get(table, table))
            for r in rows:
                total += 1
                by_contact[disp] += 1
                by_type[message.MSG_TYPES.get(message.normalize_type(r.get("local_type", "")), "其他")] += 1
                ts = int(r.get("create_time", "0") or "0")
                if ts:
                    by_day[datetime.fromtimestamp(ts).strftime("%Y-%m-%d")] += 1
    return {"days": days, "total": total, "by_contact": by_contact.most_common(15),
            "by_type": by_type.most_common(), "by_day": sorted(by_day.items())}


def media(out: str = "") -> dict:
    import export_media
    base = os.path.dirname(db.find_data_dir())
    out = out or os.path.expanduser("~/Desktop/wechat_media")
    return {"out": out, **export_media.export(base, out)}


def openfile(name: str, limit: int = 8000) -> dict:
    import glob as _g
    import read_doc
    base = os.path.dirname(db.find_data_dir())
    matches = [m for m in _g.glob(os.path.join(base, "msg", "file", "**", f"*{name}*"), recursive=True) if os.path.isfile(m)]
    if not matches:
        return {"error": f"未在 msg/file 找到含 '{name}' 的文档"}
    return {"path": matches[0], "matches": len(matches), "content": read_doc.read_file(matches[0], limit)}


def _fmt_msg(row: dict) -> dict:
    ts = row.get("create_time", "0")
    type_key = message.normalize_type(row.get("local_type", ""))
    content = row.get("message_content", "") or ""
    is_me = message.is_my_message(row.get("real_sender_id", ""))
    is_text = type_key == "1" and not content.startswith("<")
    return {
        "time": message.format_time(ts), "_ts": int(ts or "0"),
        "direction": "[我]" if is_me else "[对方]",
        "type": message.MSG_TYPES.get(type_key, "其他"),
        "content": content[:500].replace("\n", " ") if is_text else "",
        "is_text": is_text,
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
    if cmd == "stats":
        out = [f"=== 统计(最近 {r['days']} 天, 共 {r['total']} 条) ===", "\n发言排行:"]
        out += [f"  {n:>5}  {c}" for c, n in r["by_contact"]]
        out.append("\n类型分布:")
        out += [f"  {n:>5}  {t}" for t, n in r["by_type"]]
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
    elif a.cmd == "stats":
        r = stats(a.days)
    elif a.cmd == "media":
        r = media(a.out)
    elif a.cmd == "openfile":
        r = openfile(a.name)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else _human(a.cmd, r))


if __name__ == "__main__":
    main()
