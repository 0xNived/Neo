# Adding an integration
1. Create `src/integrations/<name>/register.ts`.
2. Register narrowly scoped tools such as `<name>.search_messages` and `<name>.send_message`.
3. Mark each tool as `read`, `write`, `sensitive`, or `destructive`.
4. Return compact, typed results and stable item IDs.
5. Never log tokens or full private message bodies.
6. Add policy tests before enabling writes.

For an MCP server, implement `McpClient`, then pass its tools through `registerMcpServer`. Apply explicit risk overrides; an unknown MCP tool is treated as sensitive and approval-gated.

Keep search and send as separate tools. This makes “check messages” safe to automate while “reply” remains a visible approval decision.
