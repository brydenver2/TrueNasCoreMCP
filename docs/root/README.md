# TrueNAS MCP Server · Docker Deployment

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/runtime-docker%2Bcompose-0db7ed)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/license-MIT-purple)](../../LICENSE)

A production-ready Model Context Protocol (MCP) server for TrueNAS Core and SCALE, packaged for repeatable Docker deployments. This README focuses on containerized setups so you can expose the HTTP MCP endpoint (with optional Tailscale) and keep local installs optional.

## Why Containerize?

- Predictable builds with pinned Python/httpx/MCP versions.
- Secure perimeter: bearer auth, optional TLS termination, network isolation.
- Remote automation via Tailscale or reverse proxies without opening NAS ports.
- One-command upgrades using `docker-compose pull && docker-compose up -d`.

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- TrueNAS Core 13+ or SCALE 24.04+ with an API key
- MCP client (Claude Desktop, MCP Inspector, etc.)
- `git`, `make`, and `python3` if you plan to run tests locally

## 1. Configure Environment

```bash
git clone https://github.com/vespo92/TrueNasCoreMCP.git
cd TrueNasCoreMCP
cp .env.example .env
# Edit .env with your TrueNAS URL, API key, and MCP_ACCESS_TOKEN
```

## 2. Launch the Stack

```bash
docker-compose up -d
```

The default compose file exposes the HTTP server on `localhost:8000` and mounts persistent state for rate limiting and (optionally) Tailscale.

## 3. Validate

```bash
# Tail container logs
docker-compose logs -f

# Health check (requires the MCP access token)
curl -H "Authorization: Bearer $MCP_ACCESS_TOKEN" http://localhost:8000/health
```

## Environment Reference

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| TRUENAS_URL | ✅ | — | Base URL of your TrueNAS instance |
| TRUENAS_API_KEY | ✅ | — | API key from **Settings → API Keys** |
| MCP_ACCESS_TOKEN | ✅ | — | Bearer token for the HTTP server |
| TRUENAS_VERIFY_SSL | ❌ | true | Enforce TLS validation when calling TrueNAS |
| TRUENAS_HTTP_TIMEOUT | ❌ | 30 | HTTP timeout (seconds) |
| TRUENAS_ENABLE_DESTRUCTIVE_OPS | ❌ | false | Allow delete/destroy operations |
| LOG_LEVEL | ❌ | INFO | FastAPI/MCP log verbosity |
| ALLOWED_ORIGINS | ❌ | * | CORS allow-list for MCP clients |
| TAILSCALE_ENABLED | ❌ | false | Enable sidecar VPN (requires tun access) |
| TAILSCALE_AUTH_KEY | ❌ | — | Auth key for automatic enrollment |

See the [Docker deployment reference](DOCKER.md) for the full matrix, including MCP transport overrides and rate-limit tuning.

## Tooling & Tests

The repo ships with a batteries-included `Makefile`:

| Command | Purpose |
| --- | --- |
| `make setup` | Create a virtualenv, install runtime + dev dependencies, and scaffold `.env` |
| `make test` | Run the complete pytest suite (unit, integration, and functional directories under `tests/`) |
| `make test-minimal` | Execute `tests/functional/minimal_test.py` without pytest (handy for lightweight CI) |
| `make lint` | Run flake8 against `truenas_mcp_server/`, `tests/`, and `examples/` |
| `make format` | Apply Black + isort to the same paths |
| `make docs` | Build the MkDocs site under `docs/` |

Pytest automatically discovers:

- `tests/unit/**` – fast feedback for helpers and tools
- `tests/integration/**` – HTTP stack and client validation
- `tests/functional/**` – MCP end-to-end and smoke tests (migrated from the repo root)

Export `TRUENAS_API_KEY` (and other required env vars) before running destructive tests locally.

## Operations Cheat Sheet

| Action | Command |
| --- | --- |
| Start / rebuild | `docker-compose up -d --build` |
| Stop | `docker-compose down` |
| Follow logs | `docker-compose logs -f` |
| Tail last 100 lines | `docker-compose logs --tail=100` |
| Enter container | `docker exec -it truenas-mcp-server bash` |
| Clean volumes | `docker-compose down -v` |

## Remote Access with Tailscale

1. Create an auth key in the Tailscale admin console and add it to `.env` as `TAILSCALE_AUTH_KEY`.
2. Set `TAILSCALE_ENABLED=true` (plus optional `TAILSCALE_HOSTNAME` / `TAILSCALE_TAGS`).
3. Uncomment the `cap_add`, `devices`, and `volumes` blocks in `docker-compose.yaml` so the container can open `/dev/net/tun`.
4. Redeploy with `docker-compose up -d --build`.
5. Reach the MCP endpoint at `http://truenas-mcp:8000` from any device on your Tailnet.

## Health & Observability

- `GET /health` – readiness probe for containers, load balancers, or uptime robots.
- `GET /` – returns build metadata (git SHA, MCP version, detected TrueNAS flavor).
- `GET /mcp/list_tools` – dumps enabled tool metadata.
- Docker health status: `docker inspect truenas-mcp-server --format='{{.State.Health.Status}}'`.

## Security Hardening

- Keep `TRUENAS_VERIFY_SSL=true` unless you terminate TLS elsewhere.
- Generate a long, random `MCP_ACCESS_TOKEN` and rotate it periodically.
- Limit `ALLOWED_ORIGINS` to trusted MCP clients.
- Leave `TRUENAS_ENABLE_DESTRUCTIVE_OPS=false` unless you truly need delete/destroy capabilities.
- Front the HTTP endpoint with a reverse proxy that enforces TLS and rate limits (nginx, Traefik, Caddy, etc.).

## Additional Documentation

- [Full Docker reference](DOCKER.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [Contributing guide](CONTRIBUTING.md)
- [License](../../LICENSE)

Questions or issues? Open a ticket on [GitHub Issues](https://github.com/vespo92/TrueNasCoreMCP/issues) or start a discussion in the repository.
