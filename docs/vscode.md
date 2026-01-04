# VS Code Integration Guide

Use the Claude for VS Code extension (or any IDE client that speaks the [Model Context Protocol](https://modelcontextprotocol.io/)) to talk directly to the TrueNAS MCP server.

## Prerequisites

- VS Code 1.86+ (States/HTTP transports ship in the newer builds).
- Extension: **Claude for VS Code** (identifier: `anthropic.claude-vscode`).
- A running TrueNAS MCP server exposed over HTTP (recommended) or stdio.
- Environment variables from the main [README](../README.md#-configuration) so the server knows how to reach your appliance.

## 1. Start the MCP Server

### Option A – Docker HTTP transport

```bash
# Inside the repo
cp .env.example .env
# populate TRUENAS_URL, TRUENAS_API_KEY, MCP_ACCESS_TOKEN, etc.
docker compose up -d
```

Expose port 8000 locally (default) so VS Code can hit `http://localhost:8000/mcp`.

### Option B – Local stdio process (uvx)

```bash
uvx truenas-mcp-server
```

`uvx` installs/updates the package automatically and runs it in stdio mode, which is useful when VS Code manages the process lifecycle.

## 2. Add the Server to Claude for VS Code

1. Press `⇧⌘P` (macOS) or `Ctrl+Shift+P` (Windows/Linux).
2. Run **“Claude: Edit Configurations”**. This opens the JSON config (same structure as Claude Desktop’s `claude_desktop_config.json`).
3. Add a new entry under the `mcpServers` object.

### HTTP example (container or FastAPI server)

```json
{
  "mcpServers": {
    "truenas-http": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${env:MCP_ACCESS_TOKEN}"
      }
    }
  }
}
```

- `type: "http"` tells the extension to use the JSON-RPC-over-HTTP transport implemented by `truenas_mcp_server/http_server.py`.
- The `${env:...}` syntax keeps secrets out of the config file; VS Code resolves the value from your shell when launching the chat session.
- If you are using Tailscale or TLS termination, adjust the `url` (for example `https://nas.example/mcp`).

### stdio example (uvx / pip install)

```json
{
  "mcpServers": {
    "truenas-stdio": {
      "command": "uvx",
      "args": ["truenas-mcp-server"],
      "env": {
        "TRUENAS_URL": "https://your-truenas.local",
        "TRUENAS_API_KEY": "${env:TRUENAS_API_KEY}",
        "TRUENAS_VERIFY_SSL": "false"
      }
    }
  }
}
```

This variant lets VS Code spawn the binary on demand. Use `${workspaceFolder}` or `${env:VAR}` tokens if you keep the Talos/Tailscale configs in the repository.

## 3. Reload MCP Servers

- After editing the configuration, run **“Claude: Reload MCP Servers”** (command palette) or reload VS Code entirely.
- Open the Claude panel, run **“List available tools”**, and confirm entries such as `list_pools`, `list_datasets`, and `list_snapshots` appear. If the list is empty, check the MCP server logs (`docker logs truenas-mcp` or the uvx console output).

## Troubleshooting

- **401 Unauthorized** – ensure `MCP_ACCESS_TOKEN` in the VS Code config matches the token the server expects (see `http_api/settings.py`).
- **Connection refused** – verify the Docker container publishes port 8000 to localhost, or forward the port if you are connecting over SSH.
- **Missing task-specific tools** – include an `X-Task-Type` header when calling `/mcp` manually, or rely on Claude’s intent classifier. For manual testing you can always reuse the curl snippets from [docs/testing.md](testing.md).
- **High-latency responses** – enable VS Code’s streaming option or move the MCP server closer to the workstation to avoid double round trips through your storage network.

Once the Claude panel can invoke `tools/list`, you can script more advanced workflows directly from VS Code chat without leaving the editor.
