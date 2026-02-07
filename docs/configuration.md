# Configuration

CronAgent uses YAML configuration with environment variable support.

## Configuration File

The default configuration file is located at `~/.cronagent/config.yaml`.

You can also specify a custom path:

```bash
cronagent --config /path/to/config.yaml agent
```

## Complete Reference

```yaml
# Agent Configuration
agent:
  # Claude model to use
  model: "claude-sonnet-4-20250514"

  # Maximum conversation turns
  max_turns: 50

  # Permission mode: "default", "acceptEdits", "bypassPermissions"
  permission_mode: "acceptEdits"

  # Working directory for file operations
  working_directory: "."

  # Custom system prompt (optional)
  system_prompt: null

# Scheduler Configuration
scheduler:
  # Job store URL (SQLite or PostgreSQL)
  job_store_url: "sqlite:///~/.cronagent/jobs.db"

  # Timezone for cron expressions
  timezone: "UTC"

  # Maximum concurrent jobs
  max_concurrent_jobs: 5

  # Grace time for missed jobs (seconds)
  misfire_grace_time: 60

# Channel Configuration
channels:
  # CLI channel
  cli:
    enabled: true

  # Telegram channel
  telegram:
    enabled: false
    token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users: []  # User IDs that can interact

  # Slack channel
  slack:
    enabled: false
    webhook_url: "${SLACK_WEBHOOK_URL}"
    bot_token: "${SLACK_BOT_TOKEN}"  # For interactive bots

  # Discord channel
  discord:
    enabled: false
    webhook_url: "${DISCORD_WEBHOOK_URL}"
    bot_token: "${DISCORD_BOT_TOKEN}"  # For bots

  # Webhook channel (inbound)
  webhook:
    enabled: false
    port: 8080
    secret: "${WEBHOOK_SECRET}"

# Memory Configuration
memory:
  # Storage type: "sqlite" or "postgresql"
  storage_type: "sqlite"

  # SQLite path (for sqlite storage)
  sqlite_path: "~/.cronagent/sessions.db"

  # PostgreSQL URL (for postgresql storage)
  postgres_url: "${DATABASE_URL}"

  # Enable knowledge base (vector search)
  enable_knowledge_base: true

  # Vector store: "chromadb" or "pgvector"
  knowledge_store: "chromadb"

  # ChromaDB path
  chromadb_path: "~/.cronagent/knowledge"

# Notification Configuration
notifications:
  # Default channels for notifications
  default_channels: ["cli"]

  # Channels for failure notifications
  on_failure: ["slack", "email"]

  # Rate limiting (seconds between notifications)
  rate_limit: 60

  # Deduplication window (seconds)
  dedup_window: 300

# Job Definitions
jobs:
  - id: "example-job"
    name: "Example Daily Task"
    cron: "0 9 * * *"
    prompt: |
      Your task here
    notifications:
      on_start: []
      on_success: ["slack"]
      on_failure: ["slack", "email"]
```

## Environment Variables

Environment variables can be referenced with `${VAR}` syntax:

```yaml
channels:
  telegram:
    token: "${TELEGRAM_BOT_TOKEN}"
```

### Required Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

### Optional Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `SLACK_WEBHOOK_URL` | Slack webhook URL |
| `SLACK_BOT_TOKEN` | Slack bot token |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL |
| `DATABASE_URL` | PostgreSQL connection URL |

## Schedule Formats

### Cron Expressions

Standard 5-field cron expressions:

```yaml
cron: "0 9 * * *"      # Every day at 9am
cron: "*/15 * * * *"   # Every 15 minutes
cron: "0 0 * * MON"    # Every Monday at midnight
cron: "0 9-17 * * 1-5" # Hourly during work hours, weekdays
```

### Interval Scheduling

```yaml
schedule:
  type: interval
  hours: 1        # Run every hour

schedule:
  type: interval
  minutes: 30     # Run every 30 minutes
```

### One-Time Scheduling

```yaml
schedule:
  type: one_time
  run_at: "2025-03-15T10:00:00Z"
```

### Dependent Jobs

```yaml
schedule:
  type: dependent
  depends_on: "parent-job-id"
  delay_seconds: 60  # Wait 60s after parent completes
```

## Next Steps

- [Examples](examples.md) - See real configuration examples
- [Channels Guide](guides/channels.md) - Set up channels
- [Production Deployment](guides/docker.md) - Docker setup
