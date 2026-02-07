# CronAgent Documentation

Welcome to the CronAgent documentation! CronAgent is an autonomous agent scheduler that combines Claude's AI capabilities with cron-like scheduling.

## Quick Navigation

<div class="grid cards" markdown>

-   **Getting Started**

    ---

    Install CronAgent and run your first scheduled agent

    [:octicons-arrow-right-24: Quick Start](getting-started.md)

-   **Configuration**

    ---

    Configure agents, schedulers, channels, and more

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   **Examples**

    ---

    Real-world examples and use cases

    [:octicons-arrow-right-24: Examples](examples.md)

-   **API Reference**

    ---

    Complete API documentation

    [:octicons-arrow-right-24: API Reference](api/index.md)

</div>

## What is CronAgent?

CronAgent is a **lightweight autonomous agent scheduler** (~5,000 lines) that lets you:

- **Schedule AI tasks** with cron expressions
- **Automate workflows** across Telegram, Slack, Discord
- **Deploy self-managing agents** with cross-session memory
- **Pass CLI credentials** (GitHub, AWS) to Claude

## Key Features

| Feature | Description |
|---------|-------------|
| **Scheduled Tasks** | Cron expressions, intervals, dependencies |
| **Multi-Channel** | Telegram, Slack, Discord, Webhooks |
| **Memory** | Session persistence and cross-session learning |
| **Knowledge Base** | Vector search over your codebase |
| **Notifications** | Smart alerts with deduplication |

## Installation

```bash
# From PyPI
pip install cronagent

# With all integrations
pip install "cronagent[all]"
```

## Quick Example

```bash
# Initialize configuration
cronagent init

# Set API key
export ANTHROPIC_API_KEY=your-key

# Run a task
cronagent run "Analyze this codebase and suggest improvements"

# Start the scheduler daemon
cronagent daemon
```

## Support

- [GitHub Issues](https://github.com/cronagent/cronagent/issues) - Bug reports
- [GitHub Discussions](https://github.com/cronagent/cronagent/discussions) - Questions
- [Discord](https://discord.gg/cronagent) - Community chat
