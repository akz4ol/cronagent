#!/bin/bash
set -e

# CronAgent Docker Entrypoint
# Handles initialization and command routing

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Ensure config directory exists
mkdir -p "${CRONAGENT_HOME:-/home/cronagent/.cronagent}"

# Initialize config if not present
if [ ! -f "${CRONAGENT_HOME}/config.yaml" ]; then
    log_info "No config found, initializing with defaults..."

    # Check for mounted config
    if [ -f "/config/config.yaml" ]; then
        log_info "Using mounted config from /config/config.yaml"
        cp /config/config.yaml "${CRONAGENT_HOME}/config.yaml"
    else
        # Create default config
        cat > "${CRONAGENT_HOME}/config.yaml" << 'EOF'
# CronAgent Configuration (Docker)
# Generated automatically on first run

agent:
  model: "claude-sonnet-4-20250514"
  max_turns: 50
  permission_mode: "acceptEdits"

scheduler:
  job_store_url: "sqlite:///~/.cronagent/jobs.db"
  timezone: "UTC"
  max_concurrent_jobs: 5

memory:
  storage_type: "sqlite"
  sqlite_path: "~/.cronagent/sessions.db"
  enable_knowledge_base: true
  knowledge_store: "chromadb"
  chromadb_path: "~/.cronagent/knowledge"

channels:
  cli:
    enabled: true
  webhook:
    enabled: true
    port: 8080
    path: "/webhook"

notifications:
  default_channels: ["console"]
  on_job_failure: true

log_level: "INFO"
EOF
        log_info "Created default configuration"
    fi
fi

# Validate required environment variables
if [ -z "${ANTHROPIC_API_KEY}" ]; then
    log_error "ANTHROPIC_API_KEY environment variable is required"
    log_error "Set it with: docker run -e ANTHROPIC_API_KEY=your-key ..."
    exit 1
fi

# Optional: Check for other useful env vars
if [ -n "${GITHUB_TOKEN}" ]; then
    log_info "GitHub token detected"
fi

if [ -n "${SLACK_WEBHOOK_URL}" ]; then
    log_info "Slack webhook configured"
fi

if [ -n "${DISCORD_WEBHOOK_URL}" ]; then
    log_info "Discord webhook configured"
fi

# Handle commands
case "${1:-daemon}" in
    daemon)
        log_info "Starting CronAgent daemon..."
        exec cronagent daemon
        ;;
    agent)
        log_info "Starting CronAgent interactive mode..."
        exec cronagent agent
        ;;
    run)
        shift
        log_info "Running single task..."
        exec cronagent run "$@"
        ;;
    cron)
        shift
        exec cronagent cron "$@"
        ;;
    status)
        exec cronagent status
        ;;
    init)
        log_info "Reinitializing configuration..."
        rm -f "${CRONAGENT_HOME}/config.yaml"
        exec cronagent init
        ;;
    shell)
        log_info "Starting shell..."
        exec /bin/bash
        ;;
    *)
        # Pass through to cronagent
        exec cronagent "$@"
        ;;
esac
