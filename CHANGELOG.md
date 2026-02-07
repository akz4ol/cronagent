# Changelog

All notable changes to CronAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-07

### Added
- Initial release of CronAgent
- Core agent loop with Claude SDK integration
- Session persistence with SQLite/PostgreSQL
- Cross-session memory and learning
- Knowledge base with vector search (ChromaDB/pgvector)
- Scheduler with cron/interval/one-time/dependent jobs
- Multi-channel notifications (Telegram, Slack, Discord)
- Webhook support for inbound triggers
- Docker deployment with multi-stage builds
- Docker Compose profiles (dev, production, monitoring)
- CLI commands for job management
- Event bus for component communication
- Notification deduplication and rate limiting
- Retry logic with exponential backoff

### Technical
- Python 3.11+ support
- Type hints throughout codebase
- Async-first architecture
- SQLAlchemy 2.0 with async support
- APScheduler for job scheduling
- Rich CLI with Click

[Unreleased]: https://github.com/cronagent/cronagent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cronagent/cronagent/releases/tag/v0.1.0
