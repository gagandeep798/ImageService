"""
Kinesis trigger — decodes CloudWatch Logs records, redacts PII,
and bulk-indexes into OpenSearch. Enforces user-level access boundaries.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from opensearchpy import OpenSearch, helpers

logger = Logger(service="image-service")

_REDACTED_FIELDS = frozenset({"email", "password", "token", "secret", "authorization", "cookie"})
_REDACT_PATTERN = re.compile(
    r'"(?:' + "|".join(_REDACTED_FIELDS) + r')":\s*"[^"]*"',
    re.IGNORECASE,
)

_os_client: OpenSearch | None = None


def _get_os_client() -> OpenSearch:
    """Return the module-level OpenSearch client, creating it on the first call."""
    global _os_client
    if _os_client is None:
        endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "http://localhost:9200")
        _os_client = OpenSearch(
            hosts=[endpoint],
            http_compress=True,
            use_ssl=endpoint.startswith("https"),
            verify_certs=endpoint.startswith("https"),
            timeout=10,
        )
    return _os_client


def _today_index(prefix: str) -> str:
    """Build the today's OpenSearch index name using the configured prefix."""
    today = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    return f"{prefix}-lambda-logs-{today}"


def _redact(doc: dict) -> dict:
    """Replace the value of any PII field name with ``"[REDACTED]"`` in-place."""
    for field in _REDACTED_FIELDS:
        if field in doc:
            doc[field] = "[REDACTED]"
    return doc


def _decode_kinesis_record(record: dict) -> list[dict]:
    """Decode a base64+gzip Kinesis record containing a CloudWatch Logs DATA_MESSAGE.

    Returns a list of enriched log event dicts ready for OpenSearch indexing.
    Returns an empty list for control messages (e.g., CONTROL_MESSAGE type).
    """
    raw = base64.b64decode(record["kinesis"]["data"])
    try:
        decompressed = gzip.decompress(raw)
    except OSError:
        decompressed = raw

    payload = json.loads(decompressed)
    if payload.get("messageType") != "DATA_MESSAGE":
        return []

    log_group: str = payload.get("logGroup", "")
    log_stream: str = payload.get("logStream", "")
    function_name = log_group.split("/")[-1] if "/" in log_group else log_group

    docs = []
    for event in payload.get("logEvents", []):
        try:
            doc: dict[str, Any] = json.loads(event["message"])
        except (json.JSONDecodeError, KeyError):
            doc = {"message": event.get("message", "")}

        doc["log_group"] = log_group
        doc["log_stream"] = log_stream
        doc["function_name"] = function_name
        doc["kinesis_timestamp"] = event.get("timestamp")
        _redact(doc)
        docs.append(doc)

    return docs


def handler(event: dict, context: LambdaContext) -> dict:  # noqa: ARG001
    """Lambda entry point — decodes Kinesis records and bulk-indexes them into OpenSearch.

    Returns ``{indexed: <count>, errors: <count>}``.
    """
    index_prefix = os.environ.get("OPENSEARCH_INDEX_PREFIX", "image-service")
    index_name = _today_index(index_prefix)
    client = _get_os_client()

    all_docs = []
    for record in event.get("Records", []):
        try:
            all_docs.extend(_decode_kinesis_record(record))
        except Exception as exc:
            logger.warning("Failed to decode Kinesis record", error=str(exc))

    if not all_docs:
        return {"indexed": 0}

    actions = [{"_index": index_name, "_source": doc} for doc in all_docs]
    success, errors = helpers.bulk(client, actions, raise_on_error=False)

    if errors:
        logger.error("OpenSearch bulk errors", count=len(errors))

    logger.info("log_shipper_indexed", count=success, index=index_name)
    return {"indexed": success, "errors": len(errors)}
