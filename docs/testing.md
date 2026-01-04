# HTTP Smoke Testing Guide

Use these curl snippets to validate a running TrueNAS MCP HTTP server exposed on `http://localhost:8000`. Set the following environment variables (or inline values) before running the commands:

- `MCP_ACCESS_TOKEN` – token that authorizes MCP HTTP requests
- `TRUENAS_URL` – HTTPS endpoint for your appliance (already baked into the container)
- `TRUENAS_API_KEY` – API key with read privileges (write/destructive ops not required for these checks)
- `TRUENAS_VERIFY_SSL=false` if you are using self-signed certificates

> Replace `test-token-123` with the token you configured when starting the container.

## 1. Server Health

```bash
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8000/ | jq
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize"
      }' | jq
```

## 2. Storage Operations (Read-Only)

```bash
# List datasets (children omitted to reduce payload)
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H 'X-Task-Type: storage' \
  -d '{
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
          "name": "list_datasets",
          "arguments": {
            "limit": 10,
            "include_children": false
          }
        }
      }' | jq

# Inspect a single dataset
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -d '{
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
          "name": "get_dataset",
          "arguments": {
            "dataset": "Stor1/Media",
            "include_children": false
          }
        }
      }' | jq
```

## 3. Sharing Endpoints

```bash
# Discover available sharing tools
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H 'X-Task-Type: sharing' \
  -d '{
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/list"
      }' | jq

# List SMB shares
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -d '{
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
          "name": "list_smb_shares",
          "arguments": {"limit": 20}
        }
      }' | jq
```

## 4. Snapshot Verification

```bash
# List available snapshot tools (verifies gating aliases)
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H 'X-Task-Type: snapshot' \
  -d '{
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/list"
      }' | jq

# List snapshots (limit 10)
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H 'X-Task-Type: snapshot' \
  -d '{
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
          "name": "list_snapshots",
          "arguments": {"limit": 10}
        }
      }' | jq
```

## 5. SCALE Apps (if enabled)

```bash
# List SCALE app tools
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H 'X-Task-Type: apps' \
  -d '{
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/list"
      }' | jq

# Enumerate apps (returns empty array if none deployed)
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H 'X-Task-Type: apps' \
  -d '{
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
          "name": "list_apps",
          "arguments": {"limit": 20}
        }
      }' | jq
```

These commands perform only read-only operations and can be integrated into CI smoke tests or manual validation checklists after deploying a new image.
