#!/bin/bash

# Quick start script for TrueNAS MCP Server Docker deployment

set -e

echo "🚀 TrueNAS MCP Server - Docker Quick Start"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env with your TrueNAS details:"
    echo "   - TRUENAS_URL"
    echo "   - TRUENAS_API_KEY"
    echo "   - MCP_ACCESS_TOKEN"
    echo ""
    read -p "Press Enter after you've edited .env, or Ctrl+C to exit..."
fi

# Validate required variables
echo "🔍 Validating configuration..."
source .env

if [ -z "$TRUENAS_URL" ] || [ "$TRUENAS_URL" = "https://your-truenas-ip-or-hostname" ]; then
    echo "❌ Error: TRUENAS_URL not configured in .env"
    exit 1
fi

if [ -z "$TRUENAS_API_KEY" ] || [ "$TRUENAS_API_KEY" = "your-api-key-here" ]; then
    echo "❌ Error: TRUENAS_API_KEY not configured in .env"
    exit 1
fi

if [ -z "$MCP_ACCESS_TOKEN" ] || [ "$MCP_ACCESS_TOKEN" = "your-random-secure-token-here" ]; then
    echo "❌ Error: MCP_ACCESS_TOKEN not configured in .env"
    exit 1
fi

echo "✅ Configuration validated"
echo ""

# Build and start
echo "🐳 Building Docker image..."
docker-compose build

echo ""
echo "🚀 Starting TrueNAS MCP Server..."
docker-compose up -d

echo ""
echo "⏳ Waiting for server to be ready..."
sleep 5

# Check health
echo ""
echo "🏥 Checking health..."
for i in {1..10}; do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Server is healthy!"
        break
    fi
    if [ $i -eq 10 ]; then
        echo "❌ Server failed to become healthy"
        echo ""
        echo "📋 Recent logs:"
        docker-compose logs --tail=20
        exit 1
    fi
    sleep 2
done

echo ""
echo "🎉 TrueNAS MCP Server is running!"
echo ""
echo "📊 Server Info:"
echo "   URL: http://localhost:8000"
echo "   Health: http://localhost:8000/health"
echo "   Tools: http://localhost:8000/mcp/list_tools"
echo ""
echo "🔑 Authentication:"
echo "   Use 'Authorization: Bearer $MCP_ACCESS_TOKEN' header"
echo ""
echo "📝 Useful Commands:"
echo "   docker-compose logs -f              # View logs"
echo "   docker-compose down                 # Stop server"
echo "   docker-compose restart              # Restart server"
echo "   docker exec -it truenas-mcp-server bash  # Shell access"
echo ""
echo "🧪 Test the server:"
echo "   curl -H 'Authorization: Bearer $MCP_ACCESS_TOKEN' http://localhost:8000/health"
echo ""
