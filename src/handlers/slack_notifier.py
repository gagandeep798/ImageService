"""SNS trigger — formats CloudWatch alarms as Slack messages with runbook links."""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="image-service")

_RUNBOOK_MAP: dict[str, str] = {
    "upload.failed": "runbooks/dlq-has-messages.md",
    "dynamodb.connection_errors": "runbooks/dynamodb-throttling.md",
    "scan.threat_detected": "runbooks/dlq-has-messages.md",
    "secrets.unexpected_change": "runbooks/gdpr-erasure-request.md",
    "FinalizeDLQ": "runbooks/dlq-has-messages.md",
    "ScanDLQ": "runbooks/dlq-has-messages.md",
    "DynamoDBThrottled": "runbooks/dynamodb-throttling.md",
    "LambdaErrors": "runbooks/lambda-errors.md",
    "S3ReplicationLag": "runbooks/s3-replication-lag.md",
    "DynamoDBReplicationLag": "runbooks/dynamodb-replication-lag.md",
}

_SEVERITY_EMOJI: dict[str, str] = {
    "ALARM": ":red_circle:",
    "OK": ":large_green_circle:",
    "INSUFFICIENT_DATA": ":white_circle:",
}


def _find_runbook(alarm_name: str) -> Optional[str]:
    """Return the runbook path for an alarm name using keyword matching, or None if not found."""
    for key, runbook in _RUNBOOK_MAP.items():
        if key.lower() in alarm_name.lower():
            return runbook
    return None


def _build_slack_message(alarm: dict) -> dict:
    """Build a Slack message payload from a CloudWatch alarm state-change notification.

    Includes the alarm name, new state, reason, and a runbook link if one is found.
    """
    name = alarm.get("AlarmName", "Unknown Alarm")
    state = alarm.get("NewStateValue", "ALARM")
    reason = alarm.get("NewStateReason", "")
    emoji = _SEVERITY_EMOJI.get(state, ":warning:")
    runbook = _find_runbook(name)
    runbook_text = f"\n*Runbook*: `{runbook}`" if runbook else ""

    return {
        "text": f"{emoji} *{name}* transitioned to *{state}*\n{reason}{runbook_text}",
        "username": "ImageService Alerts",
        "icon_emoji": ":bell:",
    }


def _post_to_slack(webhook_url: str, message: dict) -> None:
    """POST a message dict to the Slack incoming webhook URL."""
    body = json.dumps(message).encode()
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        if r.status not in (200, 204):
            logger.warning("Slack returned non-200", status=r.status)


def handler(event: dict, context: LambdaContext) -> dict:  # noqa: ARG001
    """Lambda entry point — formats CloudWatch alarm SNS notifications and posts them to Slack."""
    from src.common.config import get_settings
    webhook_url = get_settings().slack_webhook_url
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not configured")
        return {"ok": False}

    for record in event.get("Records", []):
        try:
            sns_message = json.loads(record.get("Sns", {}).get("Message", "{}"))
            slack_msg = _build_slack_message(sns_message)
            _post_to_slack(webhook_url, slack_msg)
            logger.info("slack_notification_sent", alarm=sns_message.get("AlarmName"))
        except Exception as exc:
            logger.exception("Failed to send Slack notification", error=str(exc))

    return {"ok": True}
