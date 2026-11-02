"""The SNS topic of the business alerts, shared by the alerts jobs.

Every job of the alerts task that e-mails someone publishes here: the
supervisor escalations (escalation.py, HU-31) and the compliance summary
(compliance_summary.py, HU-34). Each message carries the attribute
``audience`` so every e-mail subscription keeps only its own messages
(team decision of 2026-10-14, SNS filters per recipient).
"""

import os

from shared.aws import cliente

# A topic name (LocalStack: created by infra/localstack/init/01_messaging.py)
# or its ARN (AWS: securepay-<env>-business-alerts).
TOPIC = os.getenv("BUSINESS_ALERTS_TOPIC", "business-alerts")

_topic_arn: str | None = None


def _client():
    return cliente("sns")


def topic_arn(sns) -> str:
    """The ARN as given, or the ARN of the topic with that name
    (create_topic is idempotent: it returns the existing topic)."""
    global _topic_arn
    if TOPIC.startswith("arn:"):
        return TOPIC
    if _topic_arn is None:
        _topic_arn = sns.create_topic(Name=TOPIC)["TopicArn"]
    return _topic_arn


def publish(subject: str, body: str, audience: str) -> None:
    """Publish one message to BUSINESS_ALERTS_TOPIC for ``audience``.
    Raises if SNS fails, so the caller rolls back and retries next run."""
    sns = _client()
    sns.publish(
        TopicArn=topic_arn(sns),
        Subject=subject,
        Message=body,
        MessageAttributes={
            "audience": {"DataType": "String", "StringValue": audience},
        },
    )
