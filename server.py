"""WeChat MCP Server — tool handlers for reading and analyzing chat history."""
import time
from datetime import datetime

from mcp.server.fastmcp import FastMCP

import config
import contacts
import db
import message

mcp = FastMCP(
    "wechat",
    instructions=(
        "WeChat 聊天记录读取与分析工具。可以列出聊天对话、读取消息内容、搜索关键词、"
        "获取最近消息。用于分析用户的微信聊天记录，提取待办事项和行动项。\n"
        "消息中 [我] 表示用户自己发的，[对方] 表示联系人发的。"
    ),
)


@mcp.tool()
def wechat_list_chats() -> str:
    """列出所有微信聊天对话。返回联系人/群聊列表及其标识符。

    显示格式：昵称 (备注: xxx) (wxid: xxx)
    用于了解用户有哪些对话，之后可以用 wechat_read_chat 读取具体对话内容。
    支持通过昵称、备注名或 wxid 搜索联系人。"""
    name2id = db.get_name2id()
    if not name2id:
        return "未找到任何对话记录"

    lines = [f"共 {len(name2id)} 个对话:\n"]

    for table, wxid in sorted(name2id.items(), key=lambda x: x[1]):
        display = contacts.resolve_contact_name(wxid)
        lines.append(f"  {display} (wxid: {wxid})")

    return "\n".join(lines)


@mcp.tool()
def wechat_read_chat(contact: str, limit: int = 50, days: int = 7) -> str:
    """读取与指定联系人的聊天记录。

    消息中 [我] 表示用户自己发的，[对方] 表示联系人发的。

    Args:
        contact: 联系人的 wxid、昵称或备注名（支持模糊匹配）
        limit: 返回的最大消息数量，默认50
        days: 读取最近几天的消息，默认7天
    """
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400

    matched = contacts.find_contact(contact, name2id)

    if not matched:
        return f"未找到匹配 '{contact}' 的联系人。请用 wechat_list_chats 查看所有对话。"

    if len(matched) > 5:
        lines = [f"匹配 '{contact}' 的联系人太多 ({len(matched)} 个)，请更精确:\n"]
        for _, wxid, display in matched[:10]:
            lines.append(f"  {display} (wxid: {wxid})")
        if len(matched) > 10:
            lines.append(f"  ... 还有 {len(matched) - 10} 个")
        return "\n".join(lines)

    results = []
    for table, wxid, display in matched:
        results.append(f"\n=== 与 {display} 的对话 (wxid: {wxid}) ===\n")

        for db_path in db.get_message_dbs():
            tables = db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")
            if table not in [t.strip() for t in tables]:
                continue

            rows = db.query(
                db_path,
                f"SELECT local_id, create_time, local_type, real_sender_id, message_content "
                f"FROM {table} WHERE create_time > {since} "
                f"ORDER BY create_time DESC LIMIT {limit};",
            )
            for row in reversed(rows):
                ts = message.format_time(row.get("create_time", "0"))
                type_key = message.normalize_type(row.get("local_type", ""))
                msg_type = message.MSG_TYPES.get(type_key, "其他")
                content = row.get("message_content", "") or ""
                sender_id = row.get("real_sender_id", "")
                is_me = message.is_my_message(sender_id)
                direction = "[我]" if is_me else "[对方]"

                if type_key in ("10000", "10002"):
                    results.append(f"  [{ts}] [系统] {msg_type}")
                    continue

                if content.startswith("<") and type_key != "1":
                    results.append(f"  [{ts}] {direction} [{msg_type}]")
                elif content.startswith("\x08") or (len(content) > 0 and ord(content[0]) > 127 and type_key != "1"):
                    results.append(f"  [{ts}] {direction} [{msg_type}]")
                else:
                    content_preview = content[:200].replace("\n", " ")
                    results.append(f"  [{ts}] {direction} {content_preview}")

    return "\n".join(results) if results else "未找到消息"


@mcp.tool()
def wechat_recent_messages(days: int = 3, limit: int = 100) -> str:
    """获取最近几天所有对话的消息概览。

    消息中 [我] 表示用户自己发的，[对方] 表示联系人发的。

    适合用于：
    - 快速了解用户最近的聊天动态
    - 提取待办事项和行动项
    - 分析用户接下来需要做什么

    Args:
        days: 获取最近几天的消息，默认3天
        limit: 每个对话最多返回的消息数，默认100
    """
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    all_msgs = []

    for db_path in db.get_message_dbs():
        tables_raw = db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")
        msg_tables = [t.strip() for t in tables_raw if t.strip().startswith("Msg_")]

        for table in msg_tables:
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, message_content "
                f"FROM {table} WHERE create_time > {since} "
                f"ORDER BY create_time DESC LIMIT {limit};",
            )
            contact = name2id.get(table, table)
            for row in rows:
                row["_contact"] = contact
            all_msgs.extend(rows)

    all_msgs.sort(
        key=lambda x: int(x.get("create_time", "0") or "0"),
        reverse=True,
    )

    if not all_msgs:
        return f"最近 {days} 天没有消息"

    by_contact: dict[str, list] = {}
    for m in all_msgs:
        c = m["_contact"]
        display = contacts.resolve_contact_name(c)
        if display not in by_contact:
            by_contact[display] = []
        by_contact[display].append(m)

    lines = [f"最近 {days} 天共 {len(all_msgs)} 条消息，涉及 {len(by_contact)} 个对话:\n"]

    for contact_name, msgs in sorted(by_contact.items(), key=lambda x: -len(x[1])):
        lines.append(f"\n--- {contact_name} ({len(msgs)} 条) ---")
        text_shown = 0
        for m in msgs:
            if text_shown >= 20:
                lines.append(f"  ... 还有更多消息")
                break
            content = m.get("message_content", "") or ""
            type_key = message.normalize_type(m.get("local_type", ""))
            sender_id = m.get("real_sender_id", "")
            is_me = message.is_my_message(sender_id)
            direction = "[我]" if is_me else "[对方]"

            if type_key == "1" and not content.startswith("<"):
                ts = message.format_time(m.get("create_time", "0"))
                content_preview = content[:300].replace("\n", " ")
                lines.append(f"  [{ts}] {direction} {content_preview}")
                text_shown += 1
            elif type_key in ("3", "34", "43", "49"):
                ts = message.format_time(m.get("create_time", "0"))
                type_name = message.MSG_TYPES.get(type_key, "其他")
                lines.append(f"  [{ts}] {direction} [{type_name}]")
                text_shown += 1

    return "\n".join(lines)


@mcp.tool()
def wechat_search_messages(keyword: str, days: int = 30, limit: int = 50) -> str:
    """在聊天记录中搜索包含关键词的消息。

    消息中 [我] 表示用户自己发的，[对方] 表示联系人发的。

    Args:
        keyword: 搜索关键词
        days: 搜索最近几天的消息，默认30天
        limit: 最多返回的消息数量，默认50
    """
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    results = []

    for db_path in db.get_message_dbs():
        tables_raw = db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")
        msg_tables = [t.strip() for t in tables_raw if t.strip().startswith("Msg_")]

        for table in msg_tables:
            safe_keyword = keyword.replace("'", "''")
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, message_content "
                f"FROM {table} "
                f"WHERE create_time > {since} "
                f"AND message_content LIKE '%{safe_keyword}%' "
                f"ORDER BY create_time DESC LIMIT {limit};",
            )
            contact = name2id.get(table, table)
            for row in rows:
                row["_contact"] = contact
            results.extend(rows)

    results.sort(
        key=lambda x: int(x.get("create_time", "0") or "0"),
        reverse=True,
    )

    if not results:
        return f"未找到包含 '{keyword}' 的消息"

    lines = [f"搜索 '{keyword}' 找到 {len(results)} 条消息:\n"]
    for m in results[:limit]:
        ts = message.format_time(m.get("create_time", "0"))
        contact_name = contacts.resolve_contact_name(m.get("_contact", "?"))
        content = (m.get("message_content", "") or "")[:300].replace("\n", " ")
        sender_id = m.get("real_sender_id", "")
        is_me = message.is_my_message(sender_id)
        direction = "[我]" if is_me else "[对方]"
        lines.append(f"  [{ts}] {contact_name} {direction}: {content}")

    return "\n".join(lines)


@mcp.tool()
def wechat_chat_summary(days: int = 3) -> str:
    """生成最近聊天的结构化摘要，方便 AI 分析用户接下来需要做什么。

    返回每个对话的最新消息，按时间排序，标注消息类型。
    消息中 [我] 表示用户自己发的，[对方] 表示联系人发的。

    AI 应该基于此分析：
    1. 别人对用户提出的请求/问题
    2. 用户答应要做但还没做的事
    3. 约定的时间/地点/计划
    4. 需要回复但还没回复的消息

    Args:
        days: 分析最近几天，默认3天
    """
    name2id = db.get_name2id()
    since = int(time.time()) - days * 86400
    conversations = {}

    for db_path in db.get_message_dbs():
        tables_raw = db.query_raw(db_path, "SELECT name FROM sqlite_master WHERE type='table';")
        msg_tables = [t.strip() for t in tables_raw if t.strip().startswith("Msg_")]

        for table in msg_tables:
            rows = db.query(
                db_path,
                f"SELECT create_time, local_type, real_sender_id, message_content "
                f"FROM {table} WHERE create_time > {since} "
                f"AND local_type = '1' "
                f"ORDER BY create_time DESC LIMIT 30;",
            )
            if not rows:
                continue
            contact_wxid = name2id.get(table, table)
            display = contacts.resolve_contact_name(contact_wxid)
            text_msgs = [
                r for r in rows
                if r.get("message_content") and not r["message_content"].startswith("<")
            ]
            if text_msgs:
                conversations[display] = text_msgs

    if not conversations:
        return f"最近 {days} 天没有文本消息"

    lines = [
        f"=== 微信聊天摘要（最近 {days} 天）===",
        f"今天是 {datetime.now().strftime('%Y-%m-%d %A')}",
        f"涉及 {len(conversations)} 个对话\n",
        "消息标记说明: [我] = 用户自己发的, [对方] = 联系人发的\n",
        "请分析以下对话，提取：",
        "1. 待办事项（别人请求我做的事）",
        "2. 承诺事项（我答应要做的事）",
        "3. 计划安排（约定的时间/活动）",
        "4. 需要回复的消息",
        "5. 可能需要跟进的事项\n",
    ]

    for contact_name, msgs in sorted(
        conversations.items(),
        key=lambda x: max(int(m.get("create_time", "0") or "0") for m in x[1]),
        reverse=True,
    ):
        lines.append(f"\n--- {contact_name} ---")
        for m in reversed(msgs[:20]):
            ts = message.format_time(m.get("create_time", "0"))
            content = m["message_content"][:500].replace("\n", " ")
            sender_id = m.get("real_sender_id", "")
            is_me = message.is_my_message(sender_id)
            direction = "[我]" if is_me else "[对方]"
            lines.append(f"  [{ts}] {direction} {content}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
