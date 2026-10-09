# Architecture

```text
voice/text -> gateway -> brain -> tool registry -> policy -> integration/MCP
                  ^                         |              |
                  |                         +-- audit log  +-- Discord/email/etc.
                  +------ session store <------ result
```

The `NeoGateway` runs a bounded tool-calling loop. It loads a session, gives the brain only the enabled integration profiles and tool descriptions, checks each requested action, executes allowed tools, stores results, and asks the brain for a final response. Each profile provides LLM-specific guidance: for example, Discord tools operate only through the bot's visible guilds, while Telegram search operates over the authenticated user's dialogs.

## Scaling boundaries

The first implementation uses in-memory sessions and an in-process registry. These interfaces can later be backed by Redis/Postgres and a worker queue without changing integration code. Run stateless gateway replicas, persist sessions centrally, and route slow tools through workers when load requires it.

An integration may be native or MCP-backed. Both become the same `RegisteredTool`, so the brain and gateway do not care how the capability is implemented.

## Suggested production services

```text
apps/gateway       HTTP/WebSocket ingress and orchestration
apps/voice         wake word, STT, and TTS
workers/tools      slow/retryable tool execution
packages/core      shared contracts
packages/policies  organization-specific safety rules
```

Keep the current single-process structure until those boundaries solve a measured deployment problem.
