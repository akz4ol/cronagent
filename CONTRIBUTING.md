# Contributing to CronAgent

Thank you for your interest in contributing to CronAgent! This document provides guidelines and instructions for contributing.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## How to Contribute

### Reporting Bugs

Before creating a bug report, please check existing issues to avoid duplicates.

When creating a bug report, include:
- A clear, descriptive title
- Steps to reproduce the issue
- Expected vs. actual behavior
- Your environment (OS, Python version, CronAgent version)
- Relevant logs or error messages

### Suggesting Features

Feature requests are welcome! Please:
- Check existing issues/discussions first
- Provide a clear use case
- Describe how it fits with CronAgent's goals

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Set up development environment**:
   ```bash
   git clone https://github.com/yourusername/cronagent.git
   cd cronagent
   pip install -e ".[dev]"
   ```
3. **Make your changes** with clear, focused commits
4. **Write or update tests** for your changes
5. **Run the test suite**:
   ```bash
   pytest
   ```
6. **Run linting**:
   ```bash
   ruff check src/
   ruff format src/
   mypy src/
   ```
7. **Submit your PR** with a clear description

## Development Setup

### Prerequisites

- Python 3.11+
- Docker (optional, for integration tests)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/cronagent.git
cd cronagent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install in development mode
pip install -e ".[dev,all]"
```

### Project Structure

```
cronagent/
├── src/cronagent/
│   ├── agent/       # Core agent loop and context
│   ├── cron/        # Scheduler, executor, job store
│   ├── channels/    # Telegram, Slack, Discord, etc.
│   ├── memory/      # Session and knowledge management
│   ├── skills/      # MCP-based tool registry
│   ├── bus/         # Event bus for communication
│   ├── notifications/ # Notification service
│   └── storage/     # Database models and access
├── tests/           # Test suite
├── docs/            # Documentation
└── config/          # Example configurations
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=cronagent

# Run specific test file
pytest tests/test_scheduler.py

# Run integration tests (requires Docker)
pytest tests/integration/ --docker
```

### Code Style

We use:
- **ruff** for linting and formatting
- **mypy** for type checking
- **Google-style docstrings**

```bash
# Format code
ruff format src/ tests/

# Check linting
ruff check src/ tests/

# Type checking
mypy src/
```

### Commit Messages

Use conventional commit format:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `style:` Formatting
- `refactor:` Code restructuring
- `test:` Tests
- `chore:` Maintenance

Example: `feat: add Discord channel integration`

## Architecture Guidelines

### Event-Driven Design

Components communicate via the EventBus:
```python
# Emitting events
await event_bus.emit(Events.JOB_COMPLETED, {"job_id": "123"})

# Subscribing to events
event_bus.subscribe("job:*", handler)
```

### Adding a New Channel

1. Create `src/cronagent/channels/newchannel.py`
2. Extend `BaseChannel` class
3. Implement required methods
4. Register in channel manager
5. Add configuration in `config.py`

### Adding a New Skill

1. Create skill in `src/cronagent/skills/builtin/`
2. Extend `Skill` base class
3. Define tools with `@tool` decorator
4. Register in skill registry

## Documentation

- Update README.md for user-facing changes
- Add docstrings to new functions/classes
- Update docs/ for major features
- Include examples where helpful

## Questions?

- Open a [GitHub Discussion](https://github.com/yourusername/cronagent/discussions)
- Join our [Discord](https://discord.gg/cronagent)

Thank you for contributing!
