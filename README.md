<div align="center">

# Neo

### Your private personal agent

Chat naturally, remember what matters, organize your life, and get things done.

**[Quick start](#quick-start) · [Architecture](#architecture) · [Configuration](#configuration) · [Security](#security)**

</div>

---

## Overview

Neo is a self-hosted personal agent for conversations, reminders, notes, links, research, and
tasks. It keeps useful context in your workspace so you can return to something later without
starting from zero.

Neo can search and read when allowed, but it asks before it writes, sends, deletes, or acts
outside your workspace. The goal is a capable daily companion that stays understandable and under
your control.

## Highlights

- 💬 **Conversation that continues** — saved chat sessions with durable memories and preferences.
- 🗂️ **Personal Organizer** — notes, bookmarks, links, task lists, and diary-style entries.
- ⏰ **Reminders that persist** — a dedicated worker checks and delivers scheduled reminders.
- 🔎 **Useful recall** — PostgreSQL full-text search, link enrichment, and optional local embeddings.
- 🧠 **Bring your own model** — Ollama, Groq, OpenRouter, Cerebras, and compatible APIs.
- 🎙️ **Voice-ready** — browser speech input and spoken replies where Web Speech is available.
- 🛡️ **Approval-first actions** — sensitive writes stay visible and require confirmation.
- 🔌 **Expandable by design** — native tools and future MCP integrations share one tool registry.

## Integrations

| Integration | Status | What it is for |
| --- | --- | --- |
| 💬 Discord bot | Available | Search messages Neo can access and prepare/send approved replies. |
| ✈️ Telegram account | Available | Search your authorised Telegram dialogs through Telethon. |
| 🌐 Web research | Available | Search public web sources and bring the useful context back to chat. |
| 🗂️ Obsidian | Available | Export Organizer notes and links as Markdown into a local vault. |
| ✉️ Email | Planned | OAuth-based Gmail/IMAP read and approval-gated sending. |
| 🖥️ Desktop control | Planned | Explicit, approval-gated local desktop actions. |
| 🔌 MCP servers | In progress | Add new capabilities through a consistent tool and permission boundary. |

Discord is intentionally **bot/OAuth only**. Neo does not support Discord self-bots or user-token
automation. Telegram account access is opt-in and uses a local session file that must stay private.

## Architecture

~~~text
Web UI / Voice / Future channels
              |
              v
      FastAPI agent gateway
              |
              +--> LLM provider --> bounded tool loop --> policy + approvals
              |                                      |
              v                                      v
   sessions / memory / Organizer              integrations + research
              |
              v
         PostgreSQL <---- reminder worker / background enrichment
~~~

PostgreSQL is Neo's source of truth. Semantic embeddings improve fuzzy recall for ordinary notes
and links; exact records such as tasks, dates, IDs, and sensitive data use structured database
lookups instead.

## Quick start

### Requirements

- Python 3.11+
- PostgreSQL 15+ recommended
- One LLM provider, either cloud-hosted or local Ollama
- Windows is the current primary development target

### 1. Install Neo

~~~powershell
cd N:\Programming\neo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[api,production,dev,voice,tunnel]"
~~~

### 2. Create your local configuration

~~~powershell
Copy-Item .env.example .env
~~~

Then configure PostgreSQL, your profile, and one model provider:

~~~dotenv
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/neo
NEO_OWNER_NAME=YourName
NEO_OWNER_TIMEZONE=Asia/Calcutta

LLM_PROVIDER=groq
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-20b
~~~

<code>.env</code> is deliberately ignored by Git. Never put keys, session files, or database exports
in a public repository.

### 3. Start the web gateway

Use Neo's launcher on Windows; it sets the event loop required by async PostgreSQL:

~~~powershell
$env:NEO_PORT = "8000"
$env:NEO_RELOAD = "true" # use false for normal use
.\.venv\Scripts\python.exe -m apps.api.run
~~~

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 4. Start the worker

In a second terminal:

~~~powershell
cd N:\Programming\neo
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m apps.worker.main
~~~

The gateway handles interactive chat. The worker handles durable reminder checks and future
retryable/background jobs.

## Configuration

Choose one provider at a time. <code>LLM_MODEL</code> overrides the provider-specific model variable.

| Provider | Required environment variables |
| --- | --- |
| Groq | <code>LLM_PROVIDER=groq</code>, <code>GROQ_API_KEY</code>, <code>GROQ_MODEL</code> |
| OpenRouter | <code>LLM_PROVIDER=openrouter</code>, <code>OPENROUTER_API_KEY</code>, <code>OPENROUTER_MODEL</code> |
| Cerebras | <code>LLM_PROVIDER=cerebras</code>, <code>CEREBRAS_API_KEY</code>, <code>CEREBRAS_MODEL</code> |
| Ollama | <code>LLM_PROVIDER=ollama</code>, <code>OLLAMA_MODEL</code>, optional <code>OLLAMA_BASE_URL</code> |

### Local Ollama

~~~powershell
ollama pull qwen2.5:3b-instruct
ollama pull nomic-embed-text # optional: local semantic Organizer search
~~~

~~~dotenv
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:3b-instruct
OLLAMA_BASE_URL=http://127.0.0.1:11434
~~~

## Use Neo

| You want to... | Example |
| --- | --- |
| Set a reminder | “Remind me to call Sam tomorrow at 6 PM.” |
| Save something | “Save this link in my project research notes.” |
| Manage tasks | “Add buy cables to my shopping list.” |
| Recall context | “What did I save about the VPS?” |
| Research | “Search for today's news about local AI models.” |
| Keep a record | “Save this as a diary entry for today.” |

Neo asks a short follow-up when required information is missing or when multiple records could
reasonably match. It should not ask you to repeat details it already knows.

## Phone and voice

### Phone access

Run the gateway, then create a temporary Cloudflare tunnel:

~~~powershell
cloudflared tunnel --url http://127.0.0.1:8000
~~~

Open the printed <code>trycloudflare.com</code> URL on your phone. Quick-tunnel URLs are temporary.
Use a named, authenticated tunnel before exposing Neo beyond your own devices.

### Voice

The web microphone button uses browser speech recognition and reads replies aloud when available.
Chrome or Edge works best over localhost or HTTPS. Allow microphone permission, tap the mic, speak,
and Neo sends the recognised text through the normal session and approval flow.

## Obsidian export

Set a local vault path:

~~~dotenv
OBSIDIAN_VAULT_PATH=C:\Users\you\Documents\NeoVault
~~~

Export Organizer content to Markdown:

~~~powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/organizer/obsidian/export
~~~

Obsidian is an interoperable Markdown export. PostgreSQL remains the canonical workspace.

## Development

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
~~~

Useful references:

- [Architecture](docs/architecture.md)
- [Adding an integration](docs/adding-an-integration.md)
- [Security](docs/security.md)

## Security

- Keep <code>.env</code>, Telegram session files, and database backups private.
- Never save passwords, API keys, seed phrases, or credentials in chat memory or Organizer notes.
- External writes and deletes are approval-gated by default.
- Organizer deletion is recoverable through Trash.
- Discord uses official bot/OAuth mode only; user-token self-bots are not supported.
- Use a strong <code>NEO_OWNER_API_KEY</code> before exposing Neo through a public tunnel.

---

<div align="center">

Built for a personal workspace, not a surveillance platform.

</div>
