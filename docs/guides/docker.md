# Docker Deployment

Deploy CronAgent using Docker for production environments.

## Quick Start

### Using Docker Run

```bash
docker run -d \
  --name cronagent \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN \
  -v cronagent-data:/data \
  -p 8080:8080 \
  --restart unless-stopped \
  cronagent/cronagent:latest
```

### Using Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  cronagent:
    image: cronagent/cronagent:latest
    container_name: cronagent
    restart: unless-stopped
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
      - TZ=UTC
    volumes:
      - cronagent-data:/data
      - ./config:/config:ro
    ports:
      - "8080:8080"

volumes:
  cronagent-data:
```

Start the service:

```bash
docker compose up -d
```

## Production Deployment

For production, use the full stack with PostgreSQL and Redis:

```bash
docker compose --profile production up -d
```

This starts:
- CronAgent with PostgreSQL backend
- PostgreSQL with pgvector extension
- Redis for distributed job queue

### Production Configuration

```yaml
services:
  cronagent-prod:
    image: cronagent/cronagent:latest
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - CRONAGENT_MEMORY__STORAGE_TYPE=postgresql
      - CRONAGENT_MEMORY__POSTGRES_URL=postgresql://user:pass@postgres:5432/cronagent
      - CRONAGENT_SCHEDULER__JOB_STORE_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: cronagent
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: cronagent
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cronagent"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres-data:
  redis-data:
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token |
| `SLACK_WEBHOOK_URL` | No | Slack webhook URL |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook URL |
| `POSTGRES_PASSWORD` | Prod | PostgreSQL password |
| `TZ` | No | Timezone (default: UTC) |

### Volume Mounts

| Path | Description |
|------|-------------|
| `/data` | Persistent data (SQLite DBs, knowledge base) |
| `/config` | Configuration files (read-only) |
| `/app/skills` | Custom skills directory |

## Monitoring

### Health Check

The container includes a health check:

```bash
docker inspect --format='{{.State.Health.Status}}' cronagent
```

### Logs

```bash
# View logs
docker compose logs -f cronagent

# View last 100 lines
docker compose logs --tail 100 cronagent
```

### Prometheus Metrics

Enable monitoring profile:

```bash
docker compose --profile monitoring up -d
```

Access:
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin)

## Updating

```bash
# Pull latest image
docker compose pull

# Recreate container
docker compose up -d
```

## Backup

### SQLite (Development)

```bash
docker cp cronagent:/data/sessions.db ./backup/
docker cp cronagent:/data/jobs.db ./backup/
```

### PostgreSQL (Production)

```bash
docker compose exec postgres pg_dump -U cronagent cronagent > backup.sql
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs cronagent

# Check if port is in use
lsof -i :8080
```

### Database Connection Issues

```bash
# Check PostgreSQL is healthy
docker compose exec postgres pg_isready

# Check Redis is healthy
docker compose exec redis redis-cli ping
```

### Permission Issues

Ensure data volumes have correct permissions:

```bash
docker compose exec cronagent chown -R cronagent:cronagent /data
```
