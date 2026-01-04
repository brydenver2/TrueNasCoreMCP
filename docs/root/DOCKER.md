# Docker Deployment Guide for TrueNAS MCP Server

This guide covers running the TrueNAS MCP Server in a Docker container with HTTP-based access for remote connections.

## Quick Start

1. **Create environment file**:
```bash
cp .env.example .env
```

2. **Edit `.env` with your configuration**:
```env
# TrueNAS Connection (Required)
TRUENAS_URL=https://your-truenas-server.local
TRUENAS_API_KEY=your-api-key-here

# MCP Server Authentication (Required)
MCP_ACCESS_TOKEN=your-secure-token-here

# Optional Settings
TRUENAS_VERIFY_SSL=true
TRUENAS_LOG_LEVEL=INFO
LOG_LEVEL=INFO
```

3. **Build and run**:
```bash
docker-compose up -d
```

4. **Check status**:
```bash
docker-compose logs -f
curl http://localhost:8000/health
```

## Configuration

### Required Environment Variables

- `TRUENAS_URL` - Your TrueNAS server URL (e.g., `https://truenas.local`)
- `TRUENAS_API_KEY` - TrueNAS API key (get from Settings → API Keys)
- `MCP_ACCESS_TOKEN` - Secure token for HTTP API authentication

### Optional Environment Variables

#### TrueNAS Settings
- `TRUENAS_VERIFY_SSL` - Verify SSL certificates (default: `true`)
- `TRUENAS_LOG_LEVEL` - Logging level (default: `INFO`)
- `TRUENAS_ENV` - Environment (default: `production`)
- `TRUENAS_HTTP_TIMEOUT` - HTTP timeout in seconds (default: `30`)
- `TRUENAS_ENABLE_DESTRUCTIVE_OPS` - Enable delete operations (default: `false`)
- `TRUENAS_ENABLE_DEBUG_TOOLS` - Enable debug tools (default: `false`)

#### HTTP Server Settings
- `LOG_LEVEL` - Server log level (default: `INFO`)
- `MCP_TRANSPORT` - Transport protocol (default: `http`)
- `ALLOWED_ORIGINS` - CORS allowed origins (comma-separated)

#### Tailscale Integration (Optional)
Enable secure remote access via Tailscale VPN:

```env
TAILSCALE_ENABLED=true
TAILSCALE_AUTH_KEY=tskey-auth-xxxxx
TAILSCALE_HOSTNAME=truenas-mcp
TAILSCALE_TAGS=tag:mcp-server
```

Required for Tailscale:
- Uncomment `cap_add`, `devices`, and `volumes` sections in `docker-compose.yaml`
- Ensure `/dev/net/tun` is available on the host

## API Access

### Authentication

All API requests require a Bearer token:

```bash
curl -H "Authorization: Bearer your-access-token" \
  http://localhost:8000/health
```

### Available Endpoints

- `GET /` - Server information
- `GET /health` - Health check
- `POST /mcp` - MCP JSON-RPC endpoint
- `GET /mcp/list_tools` - List available tools
- `GET /mcp/list_prompts` - List available prompts

### Example: List Tools

```bash
curl -H "Authorization: Bearer your-access-token" \
  http://localhost:8000/mcp/list_tools
```

### Example: Call Tool (JSON-RPC)

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer your-access-token" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "call_tool",
    "params": {
      "name": "storage_list_pools",
      "arguments": {}
    }
  }'
```

## TrueNAS API Key Setup

1. Log into your TrueNAS Web UI
2. Navigate to **Settings → API Keys**
3. Click **Add**
4. Give it a name (e.g., "MCP Server")
5. Copy the key immediately (shown only once)
6. Add to your `.env` file as `TRUENAS_API_KEY`

## Docker Commands

### Start the server
```bash
docker-compose up -d
```

### Stop the server
```bash
docker-compose down
```

### View logs
```bash
docker-compose logs -f
```

### Rebuild after changes
```bash
docker-compose up -d --build
```

### Access container shell
```bash
docker exec -it truenas-mcp-server bash
```

## Security Considerations

1. **API Tokens**: Use strong, random tokens for `MCP_ACCESS_TOKEN`
2. **SSL Verification**: Keep `TRUENAS_VERIFY_SSL=true` in production
3. **Network Isolation**: Consider using Docker networks or Tailscale
4. **CORS**: Restrict `ALLOWED_ORIGINS` to trusted domains only
5. **Destructive Operations**: Keep disabled unless needed
6. **Regular Updates**: Keep the container image updated

## Tailscale VPN Integration

For secure remote access without exposing ports:

1. **Get Tailscale Auth Key**:
   - Visit https://login.tailscale.com/admin/settings/keys
   - Create a new auth key (ephemeral recommended)
   - Add to `.env` as `TAILSCALE_AUTH_KEY`

2. **Enable in docker-compose.yaml**:
   ```yaml
   environment:
     - TAILSCALE_ENABLED=true
     - TAILSCALE_AUTH_KEY=${TAILSCALE_AUTH_KEY}
   
   volumes:
     - tailscale-state:/var/lib/tailscale
   
   cap_add:
     - NET_ADMIN
   devices:
     - /dev/net/tun:/dev/net/tun
   ```

3. **Uncomment the volumes section** at the bottom of docker-compose.yaml

4. **Access via Tailscale**:
   ```bash
   curl http://truenas-mcp:8000/health
   ```

## Troubleshooting

### Container won't start
```bash
# Check logs
docker-compose logs

# Verify environment variables
docker-compose config
```

### Can't connect to TrueNAS
```bash
# Test from container
docker exec truenas-mcp-server curl -k $TRUENAS_URL

# Check SSL settings
TRUENAS_VERIFY_SSL=false
```

### Authentication failures
```bash
# Verify token is set
docker exec truenas-mcp-server env | grep MCP_ACCESS_TOKEN

# Test with curl
curl -H "Authorization: Bearer wrong-token" http://localhost:8000/health
# Should return 403
```

### Port already in use
```bash
# Change port in docker-compose.yaml
ports:
  - "8001:8000"  # Use 8001 instead
```

## Production Deployment

### With Reverse Proxy (Recommended)

Use nginx or Traefik for SSL termination:

```nginx
server {
    listen 443 ssl;
    server_name truenas-mcp.yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Health Monitoring

The container includes a health check endpoint:

```bash
# Manual check
curl http://localhost:8000/health

# Docker health status
docker inspect truenas-mcp-server --format='{{.State.Health.Status}}'
```

### Logging

Logs are written to stdout and can be viewed with:

```bash
# Follow logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Export logs
docker-compose logs > truenas-mcp.log
```

## Architecture

```
┌─────────────────┐
│   MCP Client    │
│  (HTTP/HTTPS)   │
└────────┬────────┘
         │
         │ HTTP + Bearer Token
         ▼
┌─────────────────────┐
│  Docker Container   │
│  ┌───────────────┐  │
│  │  FastAPI      │  │
│  │  HTTP Server  │  │
│  └───────┬───────┘  │
│          │          │
│  ┌───────▼───────┐  │
│  │  TrueNAS MCP  │  │
│  │    Server     │  │
│  └───────┬───────┘  │
│          │          │
└──────────┼──────────┘
           │
           │ HTTPS + API Key
           ▼
    ┌──────────────┐
    │   TrueNAS    │
    │  Core/SCALE  │
    └──────────────┘
```

## Environment File Template

Create `.env` from this template:

```env
# TrueNAS Connection (Required)
TRUENAS_URL=https://192.168.1.100
TRUENAS_API_KEY=1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# MCP Server (Required)
MCP_ACCESS_TOKEN=your-random-secure-token-here

# Optional: TrueNAS Settings
TRUENAS_VERIFY_SSL=true
TRUENAS_LOG_LEVEL=INFO
TRUENAS_ENV=production
TRUENAS_HTTP_TIMEOUT=30
TRUENAS_ENABLE_DESTRUCTIVE_OPS=false
TRUENAS_ENABLE_DEBUG_TOOLS=false

# Optional: HTTP Server Settings
LOG_LEVEL=INFO
MCP_TRANSPORT=http
ALLOWED_ORIGINS=https://yourdomain.com

# Optional: Tailscale (uncomment to enable)
# TAILSCALE_ENABLED=true
# TAILSCALE_AUTH_KEY=tskey-auth-xxxxx
# TAILSCALE_HOSTNAME=truenas-mcp
# TAILSCALE_TAGS=tag:mcp-server
```

## Next Steps

- See [README.md](README.md) for full feature documentation
- Review [SECURITY.md](SECURITY.md) for security best practices
- Check [examples/](examples/) for usage examples
