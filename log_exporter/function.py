"""CloudWatch log exporter Lambda.

Polls CloudWatch log groups matching configured prefixes, collects recent
events, and writes NDJSON files to S3 for Vector to consume via SQS
notifications.
"""

import json
import os
import time
from datetime import datetime, timezone

import boto3

logs_client = boto3.client("logs")
s3_client = boto3.client("s3")

EXPORT_BUCKET = os.environ.get("EXPORT_BUCKET", "tops-cloudwatch-export-v2")
LAMBDA_LOG_PREFIX = os.environ.get("LAMBDA_LOG_PREFIX", "/aws/lambda/tops-")
SFN_LOG_PREFIX = os.environ.get("SFN_LOG_PREFIX", "/aws/states/tops-")
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "6"))

SKIP_PREFIXES = ("START RequestId:", "END RequestId:", "REPORT RequestId:")


def discover_log_groups(prefix):
    """Return all log group names matching the given prefix."""
    groups = []
    paginator = logs_client.get_paginator("describe_log_groups")
    for page in paginator.paginate(logGroupNamePrefix=prefix):
        for group in page.get("logGroups", []):
            groups.append(group["logGroupName"])
    return groups


def collect_events(log_group, start_time, end_time):
    """Collect all log events from a group within the time window."""
    events = []
    paginator = logs_client.get_paginator("filter_log_events")
    for page in paginator.paginate(
        logGroupName=log_group,
        startTime=start_time,
        endTime=end_time,
        interleaved=True,
    ):
        for event in page.get("events", []):
            msg = event.get("message", "")
            if msg.startswith(SKIP_PREFIXES):
                continue
            events.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        event["timestamp"] / 1000, tz=timezone.utc
                    ).isoformat(),
                    "logGroup": log_group,
                    "logStream": event.get("logStreamName", ""),
                    "message": event.get("message", ""),
                    "eventId": event.get("eventId", ""),
                }
            )
    return events


def write_to_s3(events, source_prefix):
    """Write NDJSON to S3 under the appropriate source prefix."""
    if not events:
        return

    now = datetime.now(timezone.utc)
    key = (
        f"{source_prefix}/{now.strftime('%Y/%m/%d/%H')}/"
        f"batch-{int(time.time() * 1000)}.ndjson"
    )
    body = "\n".join(json.dumps(e, separators=(",", ":")) for e in events)
    s3_client.put_object(Bucket=EXPORT_BUCKET, Key=key, Body=body.encode("utf-8"))
    print(f"Wrote {len(events)} events to s3://{EXPORT_BUCKET}/{key}")


def handler(event, context):
    now_ms = int(time.time() * 1000)
    start_time = now_ms - (LOOKBACK_MINUTES * 60 * 1000)
    end_time = now_ms

    prefixes = [
        (LAMBDA_LOG_PREFIX, "lambda"),
        (SFN_LOG_PREFIX, "stepfunction"),
    ]

    for log_prefix, source_prefix in prefixes:
        groups = discover_log_groups(log_prefix)
        print(f"Discovered {len(groups)} log groups for prefix {log_prefix}")

        events = []
        for group in groups:
            remaining = context.get_remaining_time_in_millis()
            if remaining < 30000:
                print(
                    f"WARNING: Less than 30s remaining ({remaining}ms), "
                    f"flushing partial batch for {source_prefix}"
                )
                write_to_s3(events, source_prefix)
                events = []
                return {
                    "statusCode": 200,
                    "body": "Partial flush due to timeout",
                }

            group_events = collect_events(group, start_time, end_time)
            events.extend(group_events)

        write_to_s3(events, source_prefix)

    return {"statusCode": 200, "body": "Export complete"}
