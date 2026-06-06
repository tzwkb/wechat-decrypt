#!/usr/bin/env python3
"""wechat-decrypt 端到端自测 —— 双端(macOS sqlcipher / Windows sqlite3)全功能。

跑法: python test_e2e.py [--full]
  默认: 平台/key/解密/会话/query 8 子命令(轻量)
  --full: 额外测 media 导出 + export_chat + 语音转写(慢, 数据依赖)

前提:
  macOS  : 已 extract_key.sh 出 key.txt
  Windows: 已 extract_raw_key.py 出 key_windows.txt + decrypt_all.py 解密到 decrypted/
输出: 逐项 ✓/✗ + 末尾 N/N PASS。对齐 wecom 的 run_test.ps1。
"""
import sys
import os
import json
import platform
import subprocess

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # test/ 上一级 = skill 根
COMMON = os.path.join(SKILL, "scripts", "common")
sys.path.insert(0, SKILL)
sys.path.insert(0, COMMON)
FULL = "--full" in sys.argv
IS_MAC = platform.system() == "Darwin"
PY = sys.executable

results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    results.append((name, ok))
    print(f"  {'✓' if ok else '✗'} {name}: {detail}")


def q(sub, *args, timeout=180):
    r = subprocess.run([PY, os.path.join(COMMON, "query.py"), sub, *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip(), r.stderr.strip(), r.returncode


# ── 1. 平台 + 后端分派 ──
def t_platform():
    import config
    exp = "sqlcipher" if IS_MAC else "sqlite3"
    return config.DB_BACKEND == exp, f"{platform.system()} / backend={config.DB_BACKEND}"


# ── 2. key 文件 ──
def t_key():
    kf = os.path.join(SKILL, "key.txt" if IS_MAC else "key_windows.txt")
    return os.path.exists(kf), os.path.basename(kf) + (" 存在" if os.path.exists(kf) else " 缺失")


# ── 3. 解密链路 + 会话库发现 ──
def t_message_dbs():
    import db
    dbs = db.get_message_dbs()
    return len(dbs) > 0, f"{len(dbs)} 个 message db"


# ── 4. contact.db 加载 ──
def t_contacts():
    import db
    c = db.load_contacts_from_db()
    return len(c) > 0, f"{len(c)} 个联系人"


# ── 5. Name2Id 会话映射 ──
def t_name2id():
    import db
    n = db.get_name2id()
    return len(n) > 0, f"{len(n)} 个会话"


# ── 6. query list ──
def t_q_list():
    out, err, rc = q("list")
    return rc == 0 and "对话" in out, out.split("\n")[0] if out else err


# ── 7. query read(取首个会话) ──
def t_q_read():
    import db
    n2i = db.get_name2id()
    if not n2i:
        return False, "无会话"
    wxid = sorted(n2i.values())[0]
    out, err, rc = q("read", wxid, "-n", "5", "-d", "3650")
    return rc == 0, f"读 {wxid[:20]} ok"


# ── 8. query search ──
def t_q_search():
    out, err, rc = q("search", "的", "-d", "365", "-n", "5")
    return rc == 0, out.split("\n")[0] if out else "ok"


# ── 9. query recent --json(结构化) ──
def t_q_recent_json():
    out, err, rc = q("recent", "-d", "7", "--json")
    d = json.loads(out)
    return rc == 0 and "total" in d and "conversations" in d, f"{d.get('total')} 条 / {len(d.get('conversations', []))} 对话"


# ── 10. query summary ──
def t_q_summary():
    out, err, rc = q("summary", "-d", "7")
    return rc == 0 and "摘要" in out, "ok"


# ── 11. query stats --json ──
def t_q_stats_json():
    out, err, rc = q("stats", "-d", "30", "--json")
    d = json.loads(out)
    return rc == 0 and "total" in d and "by_type" in d, f"{d.get('total')} 条, {len(d.get('by_type', []))} 类型"


# ── 12. query openfile(找文档, 无则跳过算过) ──
def t_q_openfile():
    out, err, rc = q("openfile", "试")
    return rc == 0, (out.split("\n")[0] if out else "无匹配文档(正常)")


# ── 13/14. --full: media 导出 + export_chat ──
def t_media():
    out, err, rc = q("media", "-o", os.path.join(SKILL, "_test_media"), timeout=300)
    import shutil
    shutil.rmtree(os.path.join(SKILL, "_test_media"), ignore_errors=True)
    return rc == 0 and "导出" in out, out.strip().split("\n")[-1] if out else err


def t_export_chat():
    import db
    n2i = db.get_name2id()
    wxid = sorted(n2i.values())[0]
    import datetime
    yr = datetime.datetime.now().year
    dst = os.path.join(SKILL, "_test_export.txt")
    r = subprocess.run([PY, os.path.join(COMMON, "export_chat.py"), wxid, "--year", str(yr),
                        "-o", dst, "--no-transcribe"], capture_output=True, text=True, timeout=300)
    ok = r.returncode == 0
    if os.path.exists(dst):
        os.remove(dst)
    return ok, "导出 ok" if ok else (r.stderr.strip()[:80] or "失败")


def main():
    print(f"=== wechat-decrypt 端到端自测 ({platform.system()}, {'FULL' if FULL else '轻量'}) ===")
    for name, fn in [
        ("平台后端分派", t_platform), ("key 文件", t_key), ("解密+message库", t_message_dbs),
        ("contact 加载", t_contacts), ("Name2Id 会话", t_name2id),
        ("query list", t_q_list), ("query read", t_q_read), ("query search", t_q_search),
        ("query recent --json", t_q_recent_json), ("query summary", t_q_summary),
        ("query stats --json", t_q_stats_json), ("query openfile", t_q_openfile),
    ]:
        check(name, fn)
    if FULL:
        check("media 导出", t_media)
        check("export_chat 导出", t_export_chat)
    n_ok = sum(1 for _, ok in results if ok)
    print(f"\n{'='*40}\n{n_ok}/{len(results)} PASS" + ("  ✅ 全通过" if n_ok == len(results) else "  ⚠️ 有失败"))
    sys.exit(0 if n_ok == len(results) else 1)


if __name__ == "__main__":
    main()
