# Neo

Neo is a private, local-first assistant workspace. It combines chat, durable sessions,
memory, reminders, web research, voice input/output, and an Organizer for notes, links,
bookmarks, tasks, and diary-style records.

```text
web / voice / future channels
            ↓
FastAPI gateway → LLM provider → approved tools → PostgreSQL / integrations
            ↓                        ↓
     chat sessions + memory      reminder worker / background enrichment
```

Neo is safety-oriented: reads can run automatically; writes, external sends, and destructive
changes are approval-gated. Organizer deletes are recoverable through Trash.

## What works today

- Web chat with saved conversations and session continuity.
- PostgreSQL-backed sessions, durable memories/preferences, reminders, approvals, and Organizer.
- Organizer collections for notes, links, bookmarks, tasks, and diary entries.
- Full-text Organizer search, link metadata extraction, optional local embeddings, and Obsidian export.
- Browser voice input/output where the browser supports the Web Speech APIs.
- LLM providers: Ollama, Groq, Cerebras, OpenRouter, and compatible OpenAI-style APIs.
- Extensible tool registry for reminders, web research, Organizer, and future MCP/native integrations.

## Requirements

- Python 3.11+.
- PostgreSQL 15+ for the complete workspace. SQLite is a lightweight fallback only.
- An LLM provider: Groq/OpenRouter/Cerebras or local Ollama.
- Windows is the current primary development target.

## Quick start — Windows + PostgreSQL

### 1. Create the virtual environment

```powershell
cd N:\Programming\neo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[api,production,dev,voice,tunnel]"
```

### 2. Configure Neo

```powershell
Copy-Item .env.example .env
```

Edit `.env`. At minimum, set PostgreSQL, your identity/time zone, and one LLM provider:

```dotenv
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/neo
NEO_OWNER_NAME=Nived
NEO_OWNER_TIMEZONE=Asia/Calcutta

# Choose one provider.
LLM_PROVIDER=groq
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

Never commit `.env`. It is ignored by Git. A configured PostgreSQL database receives Neo's
tables at startup, and Neo migrates legacy SQLite sessions/memories once.

### 3. Start the gateway

Use Neo's launcher on Windows; it configures the event loop needed by async PostgreSQL:

```powershell
$env:NEO_PORT = "8000"
$env:NEO_RELOAD = "true" # use false for normal use
.\.venv\Scripts\python.exe -m apps.api.run
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Check its live configuration at
[http://127.0.0.1:8000/v1/status](http://127.0.0.1:8000/v1/status).

### 4. Start the worker in another terminal

The gateway creates reminders; this process claims and delivers due reminders and is the home for
future retryable/background jobs.

```powershell
cd N:\Programming\neo
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m apps.worker.main
```

Leave both terminals running while using Neo.

## LLM providers

Use one provider at a time. `LLM_MODEL` overrides the provider-specific model variable.

| Provider | Required `.env` values |
| --- | --- |
| Groq | `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL` |
| OpenRouter | `LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` |
| Cerebras | `LLM_PROVIDER=cerebras`, `CEREBRAS_API_KEY`, `CEREBRAS_MODEL` |
| Ollama | `LLM_PROVIDER=ollama`, optionally `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |

### Local Ollama

```powershell
ollama pull qwen2.5:3b-instruct
```

```dotenv
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:3b-instruct
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Optional local semantic indexing:

```powershell
ollama pull nomic-embed-text
```

Embeddings enhance free-form link/note search. Exact facts—tasks, reminder times, IDs, and
sensitive typed records—continue to use deterministic PostgreSQL queries.

## Optional: use Neo from your phone

Start the gateway first, then run Cloudflare's quick tunnel in another terminal:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Open the printed `trycloudflare.com` URL on your phone. Quick-tunnel URLs are temporary and can
change after each restart. Create a named tunnel and protect Neo with authentication before
exposing it beyond your own devices.

## Voice

The web microphone button uses your browser's speech-recognition API and reads Neo's reply aloud
when supported. Chrome or Edge works best over `localhost` or HTTPS.

1. Allow microphone permission.
2. Tap the microphone, speak, then pause/stop.
3. Neo sends the recognised text through the same gateway, session, policy, and approval flow.

The Python `voice` extra installs dependencies for future local STT/TTS work; browser voice is
the current default.

## Everyday use

- **Chat:** write normally. Neo asks a focused follow-up only if a required action detail is missing
  or multiple targets are plausible.
- **Approvals:** review write/delete/send actions in the Actions panel, then approve or decline.
- **Reminders:** say what to remember and when: “Remind me to call Sam tomorrow at 6 PM.”
- **Organizer:** create collections, save links/notes/tasks, check tasks off, and restore accidental
  deletions from Trash.
- **Links:** paste a public URL. Neo saves it fast, enriches it in the background, and later searches
  the stored context when you ask about it.

## Obsidian export

Set an existing local vault path:

```dotenv
OBSIDIAN_VAULT_PATH=C:\Users\you\Documents\NeoVault
```

Then export:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/organizer/obsidian/export
```

PostgreSQL remains canonical; Obsidian is an interoperable Markdown export, not a competing source
of truth.

## Project layout

```text
apps/
  api/                 FastAPI gateway and static web app
  worker/              reminder/background worker
src/neo/
  brain/               LLM providers and prompt building
  controller/          agent/tool loop and approval handling
  integrations/        native capabilities and future MCP adapters
  memory/              sessions, extraction, and persistence
  organizer/           collections, search, enrichment, embeddings, Obsidian export
  reminders/           reminder storage and scheduling
  tools/               tool contracts, registry, execution
  policies/            permissions and risk controls
  voice/               STT/TTS/VAD boundaries
docs/                  architecture and integration/security notes
.agent/                project continuity notes for future Codex sessions
tests/                 automated tests
```

## Development checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

See [architecture](docs/architecture.md), [adding an integration](docs/adding-an-integration.md),
and [security](docs/security.md). The OSS architecture study is
[.agent/memory/oss_reference_study.md](.agent/memory/oss_reference_study.md).

## Security and integration rules

- Keep `.env`, Telegram session files, and databases private.
- Never store passwords, API keys, seed phrases, or credentials in chat memory or Organizer notes.
- Discord uses official bot/OAuth mode only; Discord self-bots/user-token automation are not supported.
- A phone tunnel is public exposure: set a strong `NEO_OWNER_API_KEY` before sharing it.
- Every integration must declare configuration, permissions/risk level, approval behavior,
  logging/redaction, and tests.

## Git workflow

`main` is the deployable branch. Keep commits focused:

```text
feat(organizer): add link metadata enrichment
fix(reminders): validate natural-language due times
docs: clarify local startup
chore: add CI smoke test
```

The personal local workflow note at `.agent/GIT_WORKFLOW.local.md` is intentionally ignored.
