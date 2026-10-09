# Security and Discord account modes

Neo accepts `DISCORD_MODE=bot` only. Discord user-account automation (“self-bots”, including `discord.py-self`) is forbidden by Discord and can result in account termination. This repository does not accept user tokens or implement that transport. Discord's official policy is explicit: [Automated User Accounts (Self-Bots)](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots).

If a capability cannot be delivered by a bot in a server, use an official OAuth flow or keep it manual. Do not work around the limitation through browser automation.

## Defaults

- External writes require human approval.
- Destructive actions are denied by the default policy.
- Unknown MCP tools are treated as sensitive.
- Tool loops have a fixed maximum round count.
- Logs redact common credential fields.
- Discord access can be restricted to an allowlist of guild IDs.

Telegram account search uses Telethon only after an interactive login with the account holder's own API ID/hash. Its session file is a credential: keep it encrypted or locally protected and never commit it. Telethon documents that session files contain the authorization material needed to log in again: [Session Files](https://docs.telethon.dev/en/stable/concepts/sessions.html).

Production deployments should add encrypted secret storage, authenticated ingress, durable audit events, per-user authorization, request rate limits, MCP server allowlists, input/output size limits, and sandboxed tool workers.
