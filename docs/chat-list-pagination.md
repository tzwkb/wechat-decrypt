# Chat list pagination

The MCP `wechat_list_chats` tool returns at most 100 chats by default. Pass the
reported `next_offset` as `offset` for the following page. `limit` accepts 1–2000;
`offset` is a nonnegative integer. The response includes the total chat count.

The CLI offers the same pagination:

```text
python scripts/common/query.py list --limit 100 --offset 0 --json
```

JSON pages contain `chats`, `count`, `total`, `limit`, `offset`, and `next_offset`.
An exhausted page has `next_offset: null`. The legacy CLI command without page
arguments still returns the full list, and `query.list_chats()` keeps its existing
list return type.
