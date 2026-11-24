# Adding an integration

MCP is one transport, not Neo's integration model. A connector can be a native
Python adapter, a standard OAuth connection, a webhook, or an MCP server. Each
route ends as the same narrowly scoped tool in Neo's registry.

## Native Python connector

Create src/neo/integrations/name/tools.py. Keep vendor SDK calls in that
folder and expose only compact, useful actions to Neo. Register an integration
profile, then register read/write tools with typed input schemas and an
explicit risk.

Then add non-secret settings to the integration catalogue, document the
environment variables in .env.example, and initialize the connector in the
application lifecycle. Never put a provider token into a prompt, response, or
browser status payload.

## Rules that keep connectors safe and usable

1. Split read and write actions. A search can be automatic; sending, deleting,
   publishing, or changing an external account remains approval-gated.
2. Return stable IDs plus short excerpts. Do not feed whole private histories
   to the model.
3. Declare a risk: read, write, sensitive, or destructive.
4. Keep an integration's configuration and health state explicit. The
   /v1/integrations endpoint is secret-free and distinguishes setup from a
   real connection.
5. Add one policy test for every write or delete tool.
6. Use OAuth or an official API whenever it exists. Do not accept copied
   browser session tokens or user-account automation tokens.

## MCP connector

Use register_mcp_server from neo.integrations.mcp.bridge. It maps remote MCP
tools into the same registry. Give known tools explicit risks; any unknown tool
defaults to sensitive, so it cannot silently act on the owner's behalf.

## Discord modes

Neo supports an official Discord bot connection. It can search or send only
where that bot is installed and permitted. A future OAuth connection can let an
owner sign in and grant supported scopes, but OAuth is not a replacement for a
user-token client.

Neo does not accept Discord user tokens or implement self-bots. Discord says
automating normal user accounts outside its OAuth2/bot API is forbidden and may
lead to account termination. See Discord's
[self-bot policy](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)
and [OAuth2 documentation](https://discord.com/developers/docs/topics/oauth2).
