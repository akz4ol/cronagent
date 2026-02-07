"""
CronAgent Web Dashboard.

Provides a beautiful, easy-to-use web interface for:
- Chatting with the agent
- Managing scheduled jobs
- Viewing run history and audit logs
- Real-time status updates
"""

from cronagent.web.app import create_app, run_dashboard

__all__ = ["create_app", "run_dashboard"]
