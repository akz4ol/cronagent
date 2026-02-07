#!/bin/bash
# CronAgent One-Line Setup Script
# Usage: curl -fsSL https://raw.githubusercontent.com/akz4ol/cronagent/main/setup.sh | bash

set -e

echo "🤖 CronAgent Setup"
echo "=================="

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)  PLATFORM=linux;;
    Darwin*) PLATFORM=mac;;
    *)       PLATFORM=unknown;;
esac

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3.11+ required. Install from https://python.org"
    exit 1
fi

# Check Python version
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$PY_VERSION" < "3.11" ]]; then
    echo "❌ Python 3.11+ required (you have $PY_VERSION)"
    exit 1
fi

echo "✓ Python $PY_VERSION detected"

# Install cronagent
echo "📦 Installing CronAgent..."
pip3 install --quiet cronagent 2>/dev/null || pip3 install --quiet -e "git+https://github.com/akz4ol/cronagent.git#egg=cronagent"

# Create config directory
CONFIG_DIR="$HOME/.cronagent"
mkdir -p "$CONFIG_DIR"

# Create simple API config file if not exists
API_FILE="$CONFIG_DIR/api.txt"
if [ ! -f "$API_FILE" ]; then
    cat > "$API_FILE" << 'EOF'
# CronAgent API Configuration
# Just add your API keys below - one per line
# Format: KEY_NAME=your_key_here

# Required: Anthropic API Key (get from https://console.anthropic.com)
ANTHROPIC_API_KEY=

# Optional: Telegram Bot Token (from @BotFather)
TELEGRAM_BOT_TOKEN=

# Optional: Slack Webhook URL
SLACK_WEBHOOK_URL=

# Optional: Discord Webhook URL
DISCORD_WEBHOOK_URL=

# Optional: GitHub Token (for GitHub integrations)
GITHUB_TOKEN=
EOF
    echo "✓ Created $API_FILE"
    echo ""
    echo "📝 NEXT STEP: Add your API key to $API_FILE"
    echo "   Open the file and add your ANTHROPIC_API_KEY"
    echo ""
    echo "   Quick edit:"
    if [ "$PLATFORM" = "mac" ]; then
        echo "   open $API_FILE"
    else
        echo "   nano $API_FILE"
    fi
else
    echo "✓ Config exists at $API_FILE"
fi

# Create shell helper
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

if ! grep -q "cronagent/api.txt" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# CronAgent API Keys" >> "$SHELL_RC"
    echo "[ -f ~/.cronagent/api.txt ] && export \$(grep -v '^#' ~/.cronagent/api.txt | xargs)" >> "$SHELL_RC"
    echo "✓ Added auto-load to $SHELL_RC"
fi

# Load now
if [ -f "$API_FILE" ]; then
    export $(grep -v '^#' "$API_FILE" | grep -v '^$' | xargs) 2>/dev/null || true
fi

echo ""
echo "✅ CronAgent installed!"
echo ""
echo "🚀 Quick Start:"
echo "   1. Edit ~/.cronagent/api.txt (add your ANTHROPIC_API_KEY)"
echo "   2. Run: source ~/.bashrc  (or restart terminal)"
echo "   3. Run: cronagent agent   (start chatting!)"
echo ""
echo "📖 More commands:"
echo "   cronagent run \"your task\"  - Run a single task"
echo "   cronagent daemon           - Start scheduler"
echo "   cronagent --help           - See all commands"
echo ""
