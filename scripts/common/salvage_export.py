#!/usr/bin/env python3
"""从 factory 损坏库抢救某联系人的消息并导出（绕过损坏 page1/root）。

流程：material 取真 salt → 解密完好页 → schema 找表 root；若 root 页损坏，
退化为「孤儿 leaf 扫描」（root 坏但数据 leaf 完好时）→ 解析记录 → 复用
export_chat 的解码/转写/格式化导出。

用法:
  python3 salvage_export.py <corrupt.db> <material> <contact> [-o out.txt] [--no-transcribe]
"""
import argparse
import os
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, SKILL_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import contacts
import salvage_btree as sb
import repair_factory as rf
import export_chat as ec


def _live_columns(table: str):
    """从能正常打开的现存库取该表列序（结构与损坏库同名表一致）。"""
    for p in db.get_message_dbs():
        tbls = {t.strip() for t in db.query_raw(p, "SELECT name FROM sqlite_master WHERE type='table';")}
        if table in tbls:
            return [r["name"] for r in db.query(p, f"PRAGMA table_info({table});")]
    return None


def salvage_records(pages, schema, table_bytes, ci):
    """返回该表的 [(local_id, value_list)]。root 完好则正常 walk；
    root 损坏则用孤儿 leaf 扫描（仅当该表是唯一损坏 root 时安全）。"""
    root = schema.get(table_bytes)
    rows = []
    if root and root in pages:
        rows = sb.walk_table(pages, root)
    else:
        # root 页损坏 → 孤儿 leaf 扫描
        def walk_pages(rt):
            seen = set(); st = [rt]
            while st:
                pn = st.pop()
                if pn in seen or pn not in pages: continue
                seen.add(pn); pg = pages[pn]; base = 100 if pn == 1 else 0
                if base >= len(pg): continue
                if pg[base] in (0x05, 0x02):
                    n = int.from_bytes(pg[base+3:base+5], "big")
                    for i in range(n):
                        po = base+12+i*2
                        if po+2 <= len(pg):
                            co = int.from_bytes(pg[po:po+2], "big")
                            if co and co+4 <= len(pg): st.append(int.from_bytes(pg[co:co+4], "big"))
                    rp = int.from_bytes(pg[base+8:base+12], "big")
                    if rp: st.append(rp)
            return seen
        reachable = set()
        for rp in schema.values():
            if rp in pages: reachable |= walk_pages(rp)
        orphan_leaf = [pn for pn in pages if pn not in reachable
                       and pages[pn][(100 if pn == 1 else 0)] == 0x0D]
        for pn in orphan_leaf:
            rows += sb._leaf_cells(pages, pages[pn], pn)
    out = []
    cti = ci["create_time"]; mci = ci["message_content"]
    for rowid, payload in rows:
        v = sb.parse_record(payload)
        if v and len(v) > mci and isinstance(v[cti], int) and v[cti] > 1600000000:
            out.append((rowid, v))
    out.sort(key=lambda x: x[1][cti])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("material", help=".material 文件（取真 salt）")
    ap.add_argument("contact")
    ap.add_argument("-o", "--output")
    ap.add_argument("--no-transcribe", action="store_true")
    a = ap.parse_args()

    raw = rf.load_raw_key()
    salt = open(a.material, "rb").read(16)
    print(f"真 salt(来自 material): {salt.hex()}", file=sys.stderr)

    data = open(a.db, "rb").read()
    pages, npg, bad = sb.decrypt_good_pages(data, salt, raw)
    print(f"解密完好页 {len(pages)}/{npg}，坏页 {bad}", file=sys.stderr)
    schema = sb.find_master_rows(pages)

    # 解析联系人 → 表名（用现存库的 name2id）
    name2id = db.get_name2id()
    matched = contacts.find_contact(a.contact, name2id)
    if not matched:
        sys.exit(f"未找到联系人 {a.contact}")
    table, wxid, display = matched[0]
    table_b = table.encode()
    cols = _live_columns(table)
    if not cols:
        sys.exit(f"无法从现存库取 {table} 列序")
    ci = {n: i for i, n in enumerate(cols)}

    recs = salvage_records(pages, schema, table_b, ci)
    if not recs:
        sys.exit("未抢救到记录")
    from datetime import datetime
    t0 = recs[0][1][ci["create_time"]]; t1 = recs[-1][1][ci["create_time"]]
    print(f"抢救 {len(recs)} 条 | {datetime.fromtimestamp(t0)} → {datetime.fromtimestamp(t1)}", file=sys.stderr)

    # Name2Id 方向：抢救损坏库自身的 Name2Id（rowid→wxid）
    my_wxid = db.get_my_wxid()
    n2i = {}
    if b"Name2Id" in schema:
        nrows = sb.walk_table(pages, schema[b"Name2Id"])
        ncols = _live_columns("Name2Id") or ["user_name"]
        uni = ncols.index("user_name") if "user_name" in ncols else 0
        for rid, payload in nrows:
            v = sb.parse_record(payload)
            if v and len(v) > uni and isinstance(v[uni], bytes):
                n2i[rid] = v[uni].decode("utf-8", "replace")
    my_rowid = next((r for r, w in n2i.items() if w == my_wxid), None)

    # 构造 export_chat 兼容 row dict
    rsi = ci.get("real_sender_id")
    rows_fmt = []
    for rowid, v in recs:
        sender_rowid = v[rsi] if rsi is not None and rsi < len(v) else None
        mc = v[ci["message_content"]]
        rows_fmt.append({
            "local_id": str(rowid),
            "server_id": str(v[ci["server_id"]]) if isinstance(v[ci["server_id"]], int) else "0",
            "create_time": str(v[ci["create_time"]]),
            "local_type": str(v[ci["local_type"]]),
            "msg_hex": mc.hex() if isinstance(mc, bytes) and mc else "",
            "is_me": "1" if (my_rowid is not None and sender_rowid == my_rowid) else "0",
            "sender_wxid": n2i.get(sender_rowid, ""),
        })

    # 语音转写（复用现存 media_0.db + voice_cache）
    voice_map = {}
    if not a.no_transcribe:
        vids = [r["server_id"] for r in rows_fmt
                if ec.message.normalize_type(r["local_type"]) == "34" and r["server_id"] != "0"]
        if vids and ec.model_cached():
            print(f"转写 {len(vids)} 条语音…", file=sys.stderr)
            voice_map = ec.transcribe_voices([{"server_id": s} for s in vids])

    my_name = contacts.resolve_nickname(my_wxid)
    peer_name = contacts.resolve_nickname(wxid)
    out = a.output or os.path.expanduser(f"~/Desktop/{a.contact}_抢救_{datetime.fromtimestamp(t0).strftime('%Y%m%d')}-{datetime.fromtimestamp(t1).strftime('%Y%m%d')}.txt")
    out = os.path.expanduser(out)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"=== {display} · 从损坏库 factory 抢救 ===\n")
        f.write(f"抢救自: {os.path.basename(a.db)}（真salt {salt.hex()[:12]}…，绕过损坏root）\n")
        f.write(f"范围: {datetime.fromtimestamp(t0)} ~ {datetime.fromtimestamp(t1)}  共 {len(rows_fmt)} 条\n\n")
        for r in rows_fmt:
            f.write(ec.format_row(r, voice_map, False, my_name, peer_name) + "\n")
    print(f"\n导出完成: {out} ({len(rows_fmt)} 条)", file=sys.stderr)


if __name__ == "__main__":
    main()
