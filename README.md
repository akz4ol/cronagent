<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/cronagent-logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/cronagent-logo-light.svg">
  <img alt="CronAgent" src="docs/assets/cronagent-logo-light.svg" width="400">
</picture>

### Autonomous AI Agents on Autopilot

**Schedule Claude-powered tasks. Automate workflows. Deploy self-managing agents.**

*"Set it. Forget it. Let Claude handle the rest."*

[![PyPI version](https://img.shields.io/pypi/v/cronagent.svg)](https://pypi.org/project/cronagent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker)](https://hub.docker.com/r/cronagent/cronagent)
[![Discord](https://img.shields.io/discord/1234567890?color=7289da&label=Discord&logo=discord&logoColor=white)](https://discord.gg/cronagent)

[One-Line Setup](#-one-line-setup) &bull; [Documentation](https://akz4ol.github.io/cronagent) &bull; [Examples](#-examples) &bull; [Discord](https://discord.gg/cronagent)

---

</div>

## ⚡ One-Line Setup

### Option 1: Python (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/akz4ol/cronagent/main/setup.sh | bash
```

### Option 2: Docker

```bash
curl -fsSL https://raw.githubusercontent.com/akz4ol/cronagent/main/docker-setup.sh | bash
```

### Option 3: pip

```bash
pip install cronagent && cronagent init
```

**That's it!** After setup, just edit `~/.cronagent/api.txt` to add your API key.

---

## 🔑 Simple API Configuration

All your API keys go in one simple text file: `~/.cronagent/api.txt`

```bash
# Just edit this file - no complicated YAML!
nano ~/.cronagent/api.txt
```

```ini
# ~/.cronagent/api.txt
# Add your keys below (get Anthropic key from https://console.anthropic.com)

ANTHROPIC_API_KEY=sk-ant-xxxxx
TELEGRAM_BOT_TOKEN=123456:ABC
SLACK_WEBHOOK_URL=https://hooks.slack.com/xxx
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx
GITHUB_TOKEN=ghp_xxxxx
```

**To reconfigure anytime:**
```bash
nano ~/.cronagent/api.txt   # Edit keys
cronagent reload            # Apply changes
```

---

## 🚀 Quick Start

```bash
# Chat with the agent
cronagent agent

# Run a single task
cronagent run "Analyze this codebase"

# Start scheduled tasks
cronagent daemon
```

---

## What is CronAgent?

CronAgent is a **lightweight autonomous agent scheduler** (~5,000 lines) that combines [Claude](https://anthropic.com/claude) with cron-like scheduling.

<div align="center">
<table>
<tr>
<td align="center" width="25%">

**Scheduled Tasks**

Cron expressions, intervals, dependencies

</td>
<td align="center" width="25%">

**Multi-Channel**

Telegram, Slack, Discord, Webhooks

</td>
<td align="center" width="25%">

**Memory**

Cross-session learning & context

</td>
<td align="center" width="25%">

**Notifications**

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

<details>
<summary><b>Compared to other frameworks</b></summary>

| Framework | Lines of Code | Complexity |
|-----------|--------------|------------|
| CronAgent | ~5,000 | Simple |
| OpenClaw | 430,000+ | Complex |
| LangChain | 200,000+ | Medium |

CronAgent is intentionally minimal. Read the entire codebase in an afternoon.

</details>

---

## 📋 Examples

### Schedule a Daily Task

```bash
# Add a job via CLI
cronagent cron add --name "Daily Report" --cron "0 9 * * *" --prompt "Generate a daily summary"
```

### Or use a simple jobs file

Create `~/.cronagent/jobs.txt`:

```ini
# Simple job definitions - one per section
# ~/.cronagent/jobs.txt

[daily-security]
name = Daily Security Scan
cron = 0 6 * * *
prompt = Scan for vulnerabilities and exposed secrets
notify = slack

[weekly-report]
name = Weekly Report
cron = 0 10 * * MON
prompt = Generate a weekly development summary
notify = slack, email
```

<details>
<summary><b>More examples</b></summary>

### PR Reviewer

```ini
[pr-review]
name = AI PR Reviewer
trigger = webhook
prompt = Review this PR for bugs and improvements
notify = github
```

### Cost Analysis

```ini
[cost-analysis]
name = Weekly Cost Analysis
cron = 0 9 * * MON
prompt = Analyze cloud spending and suggest optimizations
notify = slack
```

</details>

---

## 🛠 CLI Commands

```bash
# Core
cronagent agent              # Interactive chat
cronagent run "prompt"       # Single task
cronagent daemon             # Start scheduler
cronagent status             # Show status
cronagent reload             # Reload config

# Jobs
cronagent cron list          # List jobs
cronagent cron add           # Add job (interactive)
cronagent cron remove <id>   # Remove job
cronagent cron trigger <id>  # Run job now
cronagent cron history       # View history
```

---

## 🐳 Docker Deployment

### Quick Start

```bash
docker run -d --name cronagent \
  --env-file ~/.cronagent/api.txt \
  -v cronagent-data:/data \
  ghcr.io/akz4ol/cronagent:latest
```

### Docker Compose

```bash
cd ~/.cronagent && docker compose up -d
```

### Production (with PostgreSQL + Redis)

```bash
curl -fsSL https://raw.githubusercontent.com/akz4ol/cronagent/main/docker-compose.yml > docker-compose.yml
docker compose --profile production up -d
```

---

## 📁 File Locations

| File | Purpose |
|------|---------|
| `~/.cronagent/api.txt` | API keys (simple key=value) |
| `~/.cronagent/jobs.txt` | Scheduled jobs (optional) |
| `~/.cronagent/config.yaml` | Advanced config (optional) |
| `~/.cronagent/sessions.db` | Session memory |

---

## 🔧 Advanced Configuration

For power users, full YAML config is available:

<details>
<summary><b>~/.cronagent/config.yaml</b></summary>

```yaml
agent:
  model: "claude-sonnet-4-20250514"
  max_turns: 50

scheduler:
  timezone: "UTC"
  max_concurrent_jobs: 5

channels:
  telegram:
    enabled: true
    allowed_users: ["123456789"]
  slack:
    enabled: true
  discord:
    enabled: true

memory:
  storage_type: "sqlite"
  enable_knowledge_base: true
```

</details>

---

## 🗺 Roadmap

- [x] Core agent with Claude SDK
- [x] Session memory
- [x] Cron scheduler
- [x] Multi-channel notifications
- [x] Docker deployment
- [x] Simple text-based config
- [ ] Web dashboard
- [ ] GitHub Actions integration
- [ ] Multi-agent orchestration

---

## ⭐ Star History

<a href="https://star-history.com/#akz4ol/cronagent&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=akz4ol/cronagent&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=akz4ol/cronagent&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=akz4ol/cronagent&type=Date" />
  </picture>
</a>

---

## 🤝 Contributing

```bash
git clone https://github.com/akz4ol/cronagent.git
cd cronagent && pip install -e ".[dev]"
pytest && ruff check src/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

MIT License - see [LICENSE](LICENSE)

---

<div align="center">

**Built with [Claude](https://anthropic.com/claude)**

If CronAgent helps you, give it a ⭐!

</div>
