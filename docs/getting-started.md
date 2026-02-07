# Getting Started

This guide will help you install CronAgent and run your first scheduled AI task.

## Prerequisites

- Python 3.11 or higher
- An Anthropic API key ([get one here](https://console.anthropic.com/))
- (Optional) Docker for containerized deployment

## Installation

### From PyPI

```bash
pip install cronagent
```

### With All Integrations

```bash
pip install "cronagent[all]"
```

This includes Telegram, Slack, and Discord integrations.

### From Source

```bash
git clone https://github.com/cronagent/cronagent.git
cd cronagent
pip install -e ".[all]"
```

## Configuration

### Initialize Configuration

```bash
cronagent init
```

This creates a configuration file at `~/.cronagent/config.yaml`.

### Set Your API Key

```bash
export ANTHROPIC_API_KEY=your-key-here
```

Or add it to your shell profile for persistence.

### (Optional) Set Channel Tokens

```bash
export TELEGRAM_BOT_TOKEN=your-telegram-token
export SLACK_WEBHOOK_URL=your-slack-webhook
export DISCORD_WEBHOOK_URL=your-discord-webhook
```

## Your First Task

### Interactive Mode

Start an interactive session with the agent:

```bash
cronagent agent
```

You can now chat with the agent and ask it to perform tasks.

### Single Task

Run a single task and get the result:

```bash
cronagent run "Explain the structure of this codebase"
```

### Scheduled Task

Start the scheduler daemon:

```bash
cronagent daemon
```

Jobs defined in your configuration will run automatically.

## Adding a Scheduled Job

### Via CLI

```bash
cronagent cron add
```

Follow the interactive prompts to create a job.

### Via Configuration

Edit `~/.cronagent/config.yaml`:

```yaml
jobs:
  - id: daily-summary
    name: "Daily Project Summary"
    cron: "0 9 * * *"  # Every day at 9am
    prompt: |
      Generate a brief summary of:
      1. Recent changes to the codebase
      2. Any outstanding TODOs
      3. Potential issues to address
    notifications:
      on_complete: ["slack:#dev"]
```

Then restart the daemon:

```bash
cronagent daemon
```

## Next Steps

- [Configuration Guide](configuration.md) - Deep dive into configuration
- [Examples](examples.md) - Real-world use cases
- [Channels](guides/channels.md) - Set up Telegram, Slack, Discord
- [Docker Deployment](guides/docker.md) - Production deployment
