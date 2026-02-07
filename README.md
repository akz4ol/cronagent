<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/cronagent-logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/cronagent-logo-light.svg">
  <img alt="CronAgent" src="docs/assets/cronagent-logo-light.svg" width="400">
</picture>

### Autonomous AI Agents on Autopilot

**Schedule Claude-powered tasks. Automate workflows. Deploy self-managing AI agents.**

*"Set it. Forget it. Let Claude handle the rest."*

[![PyPI version](https://img.shields.io/pypi/v/cronagent.svg)](https://pypi.org/project/cronagent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Downloads](https://img.shields.io/pypi/dm/cronagent.svg)](https://pypi.org/project/cronagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker)](https://hub.docker.com/r/cronagent/cronagent)
[![Discord](https://img.shields.io/discord/1234567890?color=7289da&label=Discord&logo=discord&logoColor=white)](https://discord.gg/cronagent)

[Quick Start](#-quick-start) &bull; [Documentation](https://cronagent.dev/docs) &bull; [Examples](#-examples) &bull; [Discord](https://discord.gg/cronagent) &bull; [Blog](https://cronagent.dev/blog)

---

</div>

## What is CronAgent?

CronAgent is a **lightweight autonomous agent scheduler** (~5,000 lines) that combines the power of [Claude](https://anthropic.com/claude) with cron-like scheduling. Unlike complex agent frameworks with 400k+ lines, CronAgent is **readable, hackable, and production-ready**.

<div align="center">
<table>
<tr>
<td align="center" width="25%">

**Scheduled Tasks**

<img src="docs/assets/demo-schedule.gif" width="200" alt="Scheduling demo">

Cron expressions, intervals, dependencies

</td>
<td align="center" width="25%">

**Multi-Channel**

<img src="docs/assets/demo-channels.gif" width="200" alt="Channels demo">

Telegram, Slack, Discord, Webhooks

</td>
<td align="center" width="25%">

**Memory**

<img src="docs/assets/demo-memory.gif" width="200" alt="Memory demo">

Cross-session learning & context

</td>
<td align="center" width="25%">

**Notifications**

<img src="docs/assets/demo-notify.gif" width="200" alt="Notifications demo">

Smart alerts with deduplication

</td>
</tr>
</table>
</div>

## Why CronAgent?

| Traditional Cron | CronAgent |
|-----------------|-----------|
| Execute fixed scripts | Execute natural language prompts |
| Rigid, brittle scripts | Adaptive, self-correcting AI |
| No memory between runs | Cross-session learning |
| Manual error handling | Intelligent retry with reasoning |
| Single-channel output | Multi-channel notifications |

<details>
<summary><b>Compared to other agent frameworks</b></summary>

| Framework | Lines of Code | Learning Curve | Production Ready |
|-----------|--------------|----------------|------------------|
| CronAgent | ~5,000 | Low | Yes |
| OpenClaw | 430,000+ | High | Yes |
| LangChain | 200,000+ | Medium | Yes |
| AutoGPT | 50,000+ | Medium | Experimental |

CronAgent is intentionally minimal. You can read the entire codebase in an afternoon.

</details>

## Quick Start

### Installation

```bash
# From PyPI
pip install cronagent

# With all integrations (Telegram, Slack, Discord)
pip install "cronagent[all]"

# From source
git clone https://github.com/cronagent/cronagent.git
cd cronagent && pip install -e ".[all]"
```

### Setup

```bash
# Initialize configuration
cronagent init

# Set your API key
export ANTHROPIC_API_KEY=your-key-here
```

### Run Your First Agent

```bash
# Interactive mode
cronagent agent

# Run a single task
cronagent run "Analyze this repository and summarize the architecture"

# Start the scheduler daemon
cronagent daemon
```

<details>
<summary><b>Docker deployment</b></summary>

```bash
# Quick start
docker run -d \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v cronagent-data:/data \
  cronagent/cronagent:latest

# With Docker Compose
docker compose up -d

# Production (with PostgreSQL + Redis)
docker compose --profile production up -d
```

</details>

## Features

### Core Capabilities

- **Natural Language Scheduling** - Schedule tasks in plain English
- **Multi-Channel Communication** - Telegram, Slack, Discord, webhooks
- **Session Memory** - Agents remember context across runs
- **Knowledge Base** - Vector search over your codebase
- **Credential Passthrough** - GitHub, AWS, and other CLI credentials

### Scheduling Options

```yaml
# Cron expressions
schedule: "0 9 * * *"          # Every day at 9am

# Interval scheduling
schedule: "every 15 minutes"    # Run every 15 minutes

# Dependent tasks
depends_on: "security-scan"     # Run after another job completes
```

### Built-in Integrations

| Channel | Status | Description |
|---------|--------|-------------|
| CLI | Ready | Interactive command-line interface |
| Telegram | Ready | Bot integration with user whitelisting |
| Slack | Ready | Slack Bolt app + webhooks |
| Discord | Ready | Discord.py bot support |
| Webhooks | Ready | HTTP endpoints for any integration |

## Examples

<details>
<summary><b>Daily Security Scan</b></summary>

```yaml
jobs:
  - id: daily-security-scan
    name: "Daily Security Audit"
    cron: "0 6 * * *"
    prompt: |
      Perform a comprehensive security analysis:
      1. Scan for dependency vulnerabilities
      2. Check for exposed secrets in code
      3. Review recent commits for security issues
      4. Generate a summary report
    notifications:
      on_complete: ["slack:#security"]
```

</details>

<details>
<summary><b>AI PR Reviewer</b></summary>

```yaml
jobs:
  - id: pr-reviewer
    name: "AI PR Reviewer"
    trigger: webhook
    prompt: |
      Review this pull request:
      - Check code quality and patterns
      - Identify potential bugs
      - Suggest improvements
      - Verify test coverage
    notifications:
      on_complete: ["github:pr-comment"]
```

</details>

<details>
<summary><b>Weekly Codebase Report</b></summary>

```yaml
jobs:
  - id: weekly-report
    name: "Weekly Code Health Report"
    cron: "0 10 * * MON"
    prompt: |
      Generate a weekly development report:
      1. Summarize commits from the past week
      2. Identify technical debt
      3. Highlight areas needing attention
      4. Track progress on open issues
    notifications:
      on_complete: ["slack:#engineering"]
```

</details>

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CronAgent                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐│
│   │  Scheduler  │    │   Memory    │    │      Agent Core         ││
│   │  (APSched)  │───▶│  (SQLite/   │◀───│    (Claude SDK)         ││
│   │             │    │  Postgres)  │    │                         ││
│   └─────────────┘    └─────────────┘    └───────────┬─────────────┘│
│         │                   │                        │              │
│         ▼                   ▼                        ▼              │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │                       Event Bus                              │  │
│   │            (Pub/Sub for decoupled communication)             │  │
│   └─────────────────────────────────────────────────────────────┘  │
│         │                   │                        │              │
│         ▼                   ▼                        ▼              │
│   ┌───────────┐      ┌───────────┐            ┌───────────┐        │
│   │ Telegram  │      │   Slack   │     ...    │  Webhook  │        │
│   └───────────┘      └───────────┘            └───────────┘        │
│                                                                      │
│                         Channels Layer                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Everything Built So Far

<details>
<summary><b>Core Platform</b></summary>

- **Agent Loop** - Claude SDK integration with tool execution
- **Context Manager** - Conversation and session tracking
- **Event Bus** - Pub/sub for component communication

</details>

<details>
<summary><b>Scheduler</b></summary>

- **APScheduler Integration** - Cron, interval, one-time, dependent jobs
- **Job Store** - SQLite/PostgreSQL persistence
- **Executor** - Claude prompts, scripts, webhooks, Python functions
- **Retry Logic** - Exponential backoff with configurable policies

</details>

<details>
<summary><b>Channels</b></summary>

- **Telegram** - python-telegram-bot integration
- **Slack** - Slack Bolt + webhooks
- **Discord** - discord.py bot
- **CLI** - Rich interactive terminal
- **Webhooks** - HTTP endpoint handlers

</details>

<details>
<summary><b>Memory</b></summary>

- **Session Manager** - Create, resume, fork sessions
- **Message Store** - Full conversation history
- **Knowledge Base** - ChromaDB/pgvector embeddings
- **Insight Extraction** - Cross-session learning

</details>

<details>
<summary><b>Notifications</b></summary>

- **Template System** - Customizable notification formats
- **Deduplication** - Prevent notification spam
- **Rate Limiting** - Channel-specific throttling
- **Multi-Channel** - Route to Slack, Discord, email, etc.

</details>

<details>
<summary><b>Deployment</b></summary>

- **Docker** - Multi-stage production builds
- **Docker Compose** - Development and production profiles
- **PostgreSQL** - Production session storage
- **Redis** - Distributed job queue (optional)
- **Monitoring** - Prometheus + Grafana (optional)

</details>

## CLI Reference

```bash
# Core commands
cronagent init              # Initialize configuration
cronagent agent             # Start interactive mode
cronagent run "prompt"      # Execute single task
cronagent daemon            # Run scheduler daemon
cronagent status            # Show system status

# Job management
cronagent cron list         # List scheduled jobs
cronagent cron add          # Add new job interactively
cronagent cron remove <id>  # Remove a job
cronagent cron trigger <id> # Manually trigger a job
cronagent cron pause <id>   # Pause a job
cronagent cron resume <id>  # Resume a paused job
cronagent cron show <id>    # Show job details
cronagent cron history      # View execution history
```

## Configuration

```yaml
# ~/.cronagent/config.yaml

agent:
  model: "claude-sonnet-4-20250514"
  max_turns: 50
  permission_mode: "acceptEdits"

scheduler:
  job_store_url: "sqlite:///~/.cronagent/jobs.db"
  timezone: "UTC"
  max_concurrent_jobs: 5

channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users: ["123456789"]
  slack:
    enabled: true
    webhook_url: "${SLACK_WEBHOOK_URL}"

memory:
  storage_type: "sqlite"
  enable_knowledge_base: true

notifications:
  default_channels: ["slack"]
  on_failure: ["slack", "email"]
```

## Roadmap

- [x] Core agent loop with Claude SDK
- [x] Session persistence and memory
- [x] Scheduler with cron/interval support
- [x] Multi-channel notifications
- [x] Docker deployment
- [ ] Web dashboard
- [ ] GitHub Actions integration
- [ ] Workflow builder UI
- [ ] Multi-agent orchestration
- [ ] Cloud-hosted version

## Star History

<a href="https://star-history.com/#cronagent/cronagent&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=cronagent/cronagent&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=cronagent/cronagent&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=cronagent/cronagent&type=Date" />
  </picture>
</a>

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
# Development setup
git clone https://github.com/cronagent/cronagent.git
cd cronagent
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src/ && mypy src/
```

## Community

- [Discord](https://discord.gg/cronagent) - Chat with the community
- [GitHub Discussions](https://github.com/cronagent/cronagent/discussions) - Ask questions
- [Twitter](https://twitter.com/cronagent) - Follow for updates

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with [Claude](https://anthropic.com/claude) by Anthropic**

*CronAgent is not affiliated with Anthropic. Claude is a trademark of Anthropic, PBC.*

If CronAgent helps you, consider giving it a star!

</div>
