FROM python:3.12-alpine

USER root

WORKDIR /app

# Install system dependencies (including optional Tailscale)
RUN apk update && \
    apk add --no-cache bash curl gcc musl-dev libffi-dev openssl-dev tailscale iptables && \
    python3 --version

# Copy requirements first for better caching
COPY requirements.txt requirements-dev.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn[standard] python-dotenv

# Copy application code and metadata
COPY truenas_mcp_server/ ./truenas_mcp_server/
COPY docs/root/ ./docs/root/
COPY setup.py pyproject.toml MANIFEST.in ./
COPY scripts/entrypoint.sh ./scripts/

# Install the package
RUN pip install --no-cache-dir -e .

# Set permissions
RUN chmod +x /app/scripts/entrypoint.sh && \
    mkdir -p /var/lib/tailscale

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO \
    MCP_TRANSPORT=http

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "truenas_mcp_server.http_server:app", "--host", "0.0.0.0", "--port", "8000"]
