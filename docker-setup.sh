#!/bin/bash
# CronAgent Docker One-Line Setup
# Usage: curl -fsSL https://raw.githubusercontent.com/akz4ol/cronagent/main/docker-setup.sh | bash

set -e

echo "🐳 CronAgent Docker Setup"
echo "========================="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker required. Install from https://docker.com"
    exit 1
fi

echo "✓ Docker detected"

# Create config directory
CONFIG_DIR="$HOME/.cronagent"
mkdir -p "$CONFIG_DIR"

# Create simple API config file
API_FILE="$CONFIG_DIR/api.txt"
if [ ! -f "$API_FILE" ]; then
    cat > "$API_FILE" << 'EOF'
# CronAgent API Configuration
# Add your API keys below

ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
SLACK_WEBHOOK_URL=
DISCORD_WEBHOOK_URL=
EOF
    echo "✓ Created $API_FILE"
fi

# Create docker-compose.yml
cat > "$CONFIG_DIR/docker-compose.yml" << 'EOF'
services:
  cronagent:
    image: ghcr.io/akz4ol/cronagent:latest
    container_name: cronagent
    restart: unless-stopped
    env_file:
      - api.txt
    volumes:
      - ./data:/data
    ports:
      - "8080:8080"
EOF

echo "✓ Created docker-compose.yml"
echo ""
echo "📝 NEXT STEP: Add your API key"
echo "   Edit: $API_FILE"
echo ""
echo "🚀 Then start with:"
echo "   cd ~/.cronagent && docker compose up -d"
echo ""
