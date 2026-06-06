"""WeChat MCP Server —— 可选薄门面。逻辑在 scripts/common/query.py(命令行核心),这里只把工具调用转发过去。

entry 范式:命令行 query.py 为唯一核心(通用/可测/CI/分发);MCP 是可选层,每工具内部调 query。
不要 MCP 也行——直接 `python scripts/common/query.py <子命令> [--json]`。
"""
import os
import sys

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "common"))
import query  # noqa: E402

mcp = FastMCP(
    "wechat",
    instructions=(
        "WeChat 聊天记录读取与分析工具。列出会话、读取消息、搜索关键词、最近动态、结构化摘要。\n"
        "消息中 [我] 表示用户自己发的，[对方] 表示联系人发的。"
    ),
)


@mcp.tool()
def wechat_list_chats() -> str:
    """列出所有微信聊天对话(昵称/备注/wxid)。"""
    return query._human("list", query.list_chats())


@mcp.tool()
def wechat_read_chat(contact: str, limit: int = 50, days: int = 7) -> str:
    """读取与指定联系人的聊天记录。contact=wxid/昵称/备注(模糊匹配)。[我]=用户, [对方]=联系人。"""
    return query._human("read", query.read_chat(contact, limit, days))


@mcp.tool()
def wechat_recent_messages(days: int = 3, limit: int = 100) -> str:
    """最近几天所有对话的消息概览,用于提取待办/行动项。"""
    return query._human("recent", query.recent(days, limit))


@mcp.tool()
def wechat_search_messages(keyword: str, days: int = 30, limit: int = 50) -> str:
    """全文搜索包含关键词的消息。"""
    return query._human("search", query.search(keyword, days, limit))


@mcp.tool()
def wechat_chat_summary(days: int = 3) -> str:
    """最近聊天的结构化摘要,供分析待办/承诺/计划/待回复。"""
    return query._human("summary", query.summary(days))


if __name__ == "__main__":
    mcp.run()
