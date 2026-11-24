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

## Retrieval and owner context

Neo keeps three different kinds of state instead of putting everything into a
single prompt:

```text
profile facts / preferences  -> keyed, confidence-scored records
Organizer notes and links    -> source item + chunks + FTS + optional vectors
scheduled jobs               -> typed payload + delivery route + worker status
```

Profile facts are small, structured records with an owner/session source and
expiry policy.  They are injected as bounded context and are also available to
the agent through read-only memory tools.  This prevents a model from treating
its own chat history as the source of truth.

Organizer retrieval is hybrid: PostgreSQL full-text search always runs; locally
generated embeddings (when available) improve fuzzy matches across saved notes
and enriched links.  The lexical path remains the fallback, so vector setup is
an enhancement rather than a dependency.  Sensitive typed records use explicit
database queries, never semantic search.

Each Organizer item can carry a context bundle: note text plus validated web
links, image/document URLs, and absolute local paths. Local paths are saved as
references only—they are never read or uploaded merely because they were saved.
Reference labels and notes participate in retrieval; importing a file or
extracting a document needs a separate, explicit capability.

The scheduler currently delivers typed in-app jobs (notification, task, content,
and link) as one-shot or interval schedules. Future external execution must add
a dedicated, approval-gated handler; a scheduled record alone never grants an
agent new authority.
