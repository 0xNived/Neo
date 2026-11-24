# Worker application

Run durable, retryable work here: scheduled checks, long searches, summarisation, and notifications. Keep interactive voice tool calls synchronous only when they have strict timeouts.

Start it in a separate terminal from the API:

```powershell
.\.venv\Scripts\python.exe -m apps.worker.main
```

It stays open quietly while waiting for work. A successful startup now prints
`Neo worker running (...)`; use `Ctrl+C` to stop it.

The scheduler currently supports in-app notifications, task prompts, content, and links. When a job becomes due, the worker marks it ready; the authenticated web client displays it and then acknowledges delivery. Future Discord, Telegram, email, and bounded agent jobs should be added as explicit delivery handlers rather than arbitrary commands stored in the database.
