"""
EventBridge trigger on Lambda Throttles alarm — temporarily increases
reserved concurrency by 20% as auto-remediation.
"""

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="image-service")

_lambda_client = None


def _get_lambda_client() -> boto3.client:
    """Return the module-level Lambda boto3 client, creating it on first call."""
    global _lambda_client
    if _lambda_client is None:
        from src.common.config import get_settings
        _lambda_client = boto3.client("lambda", region_name=get_settings().aws_region)
    return _lambda_client


def _extract_function_name(alarm_name: str) -> str:
    """Parse the Lambda function name from an alarm name.

    Convention: ``"image-service-<FunctionName>-Throttles"``
    """
    # Alarm naming convention: "image-service-<FunctionName>-Throttles"
    parts = alarm_name.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-1])  # strip trailing metric name
    return alarm_name


def handler(event: dict, context: LambdaContext) -> dict:  # noqa: ARG001
    """Lambda entry point — increases the reserved concurrency of a throttled function by 20%.

    Triggered by EventBridge when a Lambda Throttles alarm fires.  Only acts on
    ALARM state transitions; ignores OK/INSUFFICIENT_DATA to avoid oscillation.
    """
    client = _get_lambda_client()

    detail = event.get("detail", {})
    alarm_name: str = detail.get("alarmName", "")
    state: str = detail.get("state", {}).get("value", "")

    if state != "ALARM":
        return {"ok": True, "action": "none"}

    function_name = _extract_function_name(alarm_name)
    if not function_name:
        logger.warning("Could not determine function name from alarm", alarm=alarm_name)
        return {"ok": False}

    try:
        current = client.get_function_concurrency(FunctionName=function_name)
        current_limit: int = current.get("ReservedConcurrentExecutions", 10)
        new_limit = int(current_limit * 1.2)

        client.put_function_concurrency(
            FunctionName=function_name,
            ReservedConcurrentExecutions=new_limit,
        )
        logger.info("concurrency_scaled", function=function_name, old=current_limit, new=new_limit)
        return {"ok": True, "function": function_name, "old_limit": current_limit, "new_limit": new_limit}

    except client.exceptions.ResourceNotFoundException:
        logger.warning("Lambda function not found", function=function_name)
        return {"ok": False}
    except Exception as exc:
        logger.exception("Failed to scale Lambda", function=function_name)
        return {"ok": False, "error": str(exc)}
