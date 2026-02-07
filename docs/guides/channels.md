# Channel Setup Guide

CronAgent supports multiple communication channels. This guide covers setting up each channel.

## Telegram

### Create a Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the API token you receive

### Configure CronAgent

```yaml
channels:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users:
      - "123456789"  # Your Telegram user ID
```

### Get Your User ID

Send a message to `@userinfobot` to get your Telegram user ID.

### Environment Variable

```bash
export TELEGRAM_BOT_TOKEN=your-bot-token
```

## Slack

### Webhook (Simple)

1. Go to [Slack API](https://api.slack.com/apps)
2. Create a new app or use existing
3. Enable Incoming Webhooks
4. Add webhook to a channel
5. Copy the webhook URL

```yaml
channels:
  slack:
    enabled: true
    webhook_url: "${SLACK_WEBHOOK_URL}"
```

### Bot (Interactive)

For interactive features, create a Slack Bot:

1. Create a Slack App
2. Add Bot Token Scopes: `chat:write`, `im:write`
3. Install to workspace
4. Copy the Bot Token

```yaml
channels:
  slack:
    enabled: true
    bot_token: "${SLACK_BOT_TOKEN}"
```

## Discord

### Webhook

1. Go to Server Settings > Integrations
2. Create a new Webhook
3. Copy the Webhook URL

```yaml
channels:
  discord:
    enabled: true
    webhook_url: "${DISCORD_WEBHOOK_URL}"
```

### Bot (Interactive)

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Add a Bot
4. Copy the Bot Token
5. Invite bot to your server with appropriate permissions

```yaml
channels:
  discord:
    enabled: true
    bot_token: "${DISCORD_BOT_TOKEN}"
```

## Webhooks (Inbound)

Receive webhooks from external services:

```yaml
channels:
  webhook:
    enabled: true
    port: 8080
    secret: "${WEBHOOK_SECRET}"
```

Trigger jobs via HTTP:

```bash
curl -X POST http://localhost:8080/webhook/trigger/job-id \
  -H "Authorization: Bearer $WEBHOOK_SECRET"
```

## Testing Channels

Test your channel configuration:

```bash
# Test notification to all enabled channels
cronagent notify "Test message"

# Test specific channel
cronagent notify --channel slack "Test to Slack"
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Bot not responding | Check token is correct |
| User not authorized | Add user ID to allowed_users |
| Webhook failing | Verify URL and network access |
| Rate limited | Reduce notification frequency |

### Debug Mode

Enable debug logging:

```bash
CRONAGENT_LOG_LEVEL=DEBUG cronagent daemon
```
