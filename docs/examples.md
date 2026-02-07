# Examples

Real-world examples and use cases for CronAgent.

## Development Workflows

### Daily Code Review Summary

Generate a daily summary of code changes and suggestions:

```yaml
jobs:
  - id: daily-code-review
    name: "Daily Code Review"
    cron: "0 9 * * 1-5"  # 9am on weekdays
    prompt: |
      Review the codebase for today's code review:

      1. List all commits from the last 24 hours
      2. Identify any code smells or anti-patterns
      3. Suggest refactoring opportunities
      4. Check for missing tests on new code
      5. Rate overall code quality (1-10)

      Format as a brief Slack-friendly message.
    notifications:
      on_complete: ["slack:#dev-team"]
```

### PR Auto-Reviewer

Automatically review pull requests when triggered:

```yaml
jobs:
  - id: pr-reviewer
    name: "AI PR Reviewer"
    trigger:
      type: webhook
      path: "/webhook/pr"
    prompt: |
      Review this pull request thoroughly:

      1. Check code quality and readability
      2. Identify potential bugs or edge cases
      3. Verify test coverage
      4. Suggest improvements
      5. Check for security issues

      Provide feedback in a constructive tone.
    notifications:
      on_complete: ["github:pr-comment"]
```

### Weekly Tech Debt Report

Track and report on technical debt:

```yaml
jobs:
  - id: tech-debt-report
    name: "Weekly Tech Debt Report"
    cron: "0 10 * * MON"  # Mondays at 10am
    prompt: |
      Generate a technical debt report:

      1. Scan for TODO/FIXME/HACK comments
      2. Identify deprecated dependencies
      3. Find files with high complexity
      4. List functions lacking documentation
      5. Check for dead code

      Prioritize by severity and effort to fix.
    notifications:
      on_complete: ["slack:#engineering", "email:tech-lead@company.com"]
```

## Security & Compliance

### Daily Security Scan

Automated security vulnerability scanning:

```yaml
jobs:
  - id: security-scan
    name: "Daily Security Audit"
    cron: "0 6 * * *"  # 6am daily
    prompt: |
      Perform a security audit:

      1. Check dependencies for known vulnerabilities
      2. Scan for hardcoded secrets or API keys
      3. Review authentication/authorization code
      4. Check for SQL injection risks
      5. Verify input validation

      Report only HIGH and CRITICAL issues.
    notifications:
      on_failure: ["slack:#security-alerts", "pagerduty"]
      on_success: []
```

### Compliance Check

Regular compliance verification:

```yaml
jobs:
  - id: compliance-check
    name: "Weekly Compliance Check"
    cron: "0 8 * * FRI"  # Fridays at 8am
    prompt: |
      Verify compliance requirements:

      1. Check for PII handling in code
      2. Verify logging doesn't contain sensitive data
      3. Confirm encryption is used for data at rest
      4. Check access control implementations
      5. Review audit logging

      Generate a compliance report.
    notifications:
      on_complete: ["email:compliance@company.com"]
```

## DevOps & Infrastructure

### Deployment Monitor

Monitor deployments and report status:

```yaml
jobs:
  - id: deployment-monitor
    name: "Post-Deployment Check"
    schedule:
      type: dependent
      depends_on: "deploy-production"
      delay_seconds: 300  # Wait 5 mins after deploy
    prompt: |
      Verify the production deployment:

      1. Check application health endpoints
      2. Verify database connectivity
      3. Test critical user flows
      4. Monitor error rates
      5. Check performance metrics

      Report any anomalies immediately.
    notifications:
      on_failure: ["slack:#incidents", "pagerduty"]
```

### Infrastructure Cost Analysis

Weekly cloud cost analysis:

```yaml
jobs:
  - id: cost-analysis
    name: "Weekly Cost Analysis"
    cron: "0 9 * * MON"
    prompt: |
      Analyze infrastructure costs:

      1. Summarize cloud spending by service
      2. Identify unused or underutilized resources
      3. Compare to previous week
      4. Suggest cost optimization opportunities
      5. Flag any unexpected cost spikes

      Format as a clear report with action items.
    notifications:
      on_complete: ["slack:#finance", "email:infra@company.com"]
```

## Documentation

### Auto-Documentation Update

Keep documentation in sync with code:

```yaml
jobs:
  - id: docs-update
    name: "Documentation Sync"
    cron: "0 2 * * *"  # 2am daily
    prompt: |
      Review documentation for accuracy:

      1. Check README is up to date
      2. Verify API docs match implementation
      3. Update changelog if needed
      4. Check for broken links
      5. Suggest documentation improvements

      Create PRs for any necessary updates.
    notifications:
      on_complete: ["github:create-pr"]
```

### Release Notes Generator

Generate release notes from commits:

```yaml
jobs:
  - id: release-notes
    name: "Release Notes Generator"
    trigger:
      type: webhook
      path: "/webhook/release"
    prompt: |
      Generate release notes for the new version:

      1. Categorize commits (features, fixes, docs)
      2. Highlight breaking changes
      3. Include migration instructions if needed
      4. Credit contributors
      5. Format in markdown

      Create professional, user-friendly release notes.
    notifications:
      on_complete: ["github:release"]
```

## Monitoring & Alerting

### Log Analysis

Periodic log analysis for issues:

```yaml
jobs:
  - id: log-analysis
    name: "Hourly Log Analysis"
    cron: "0 * * * *"  # Every hour
    prompt: |
      Analyze recent logs:

      1. Identify error patterns
      2. Detect anomalies in request rates
      3. Flag unusual user behavior
      4. Check for performance degradation
      5. Summarize key metrics

      Only alert if actionable issues found.
    notifications:
      on_failure: ["slack:#ops"]
```

### Uptime Verification

Regular uptime and health checks:

```yaml
jobs:
  - id: uptime-check
    name: "Service Health Check"
    cron: "*/5 * * * *"  # Every 5 minutes
    prompt: |
      Verify service health:

      1. Check all API endpoints respond
      2. Verify response times are acceptable
      3. Confirm database connections
      4. Check external service dependencies

      Report only failures.
    retry:
      max_attempts: 3
      backoff: exponential
    notifications:
      on_failure: ["pagerduty", "slack:#incidents"]
```

## Next Steps

- [Configuration](configuration.md) - Full configuration reference
- [Channels Guide](guides/channels.md) - Set up notification channels
- [Production Deployment](guides/docker.md) - Deploy to production
