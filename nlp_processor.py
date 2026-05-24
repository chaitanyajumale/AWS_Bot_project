"""
Lambda Function #2: NLP Intent Processor
Processes messages from SQS queue with partial batch failure reporting
"""

import hashlib
import json
import logging
import os
import random
import re
from datetime import datetime

import boto3

from bot_common.idempotency import claim_processing_key
from bot_common.logging_utils import configure_logging, log_event

SERVICE_NAME = "bot-nlp-processor"
logger = configure_logging(SERVICE_NAME)

dynamodb = boto3.resource("dynamodb")

CONVERSATIONS_TABLE = os.environ.get("CONVERSATIONS_TABLE", "Conversations")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "UserSessions")
CONVERSATION_TTL_DAYS = int(os.environ.get("CONVERSATION_TTL_DAYS", "30"))

INTENTS = {
    "greeting": r"\b(hi|hello|hey|greetings|good\s+(morning|afternoon|evening)|howdy|hiya)\b",
    "farewell": r"\b(bye|goodbye|see\s+you|later|farewell|take\s+care)\b",
    "help": r"\b(help|support|assist|assistance|guide|how\s+to)\b",
    "status": r"\b(status|how|what|info|information|update|progress)\b",
    "thanks": r"\b(thanks|thank\s+you|thx|appreciate|grateful)\b",
    "question": r"\b(what|when|where|who|why|how|which|can\s+you)\b",
    "problem": r"\b(issue|problem|error|bug|not\s+working|broken|fail)\b",
    "feedback": r"\b(feedback|comment|suggestion|opinion|think)\b",
}

RESPONSES = {
    "greeting": [
        "Hello! How can I help you today?",
        "Hi there! What can I do for you?",
        "Hey! I'm here to assist you.",
    ],
    "farewell": [
        "Goodbye! Have a great day!",
        "See you later! Feel free to come back anytime.",
        "Take care! I'm here if you need anything.",
    ],
    "help": [
        "I'm here to help! You can ask me about status updates, support, and general questions.",
        "I'd be happy to assist! What do you need help with?",
        "Let me know what you're looking for, and I'll do my best to help!",
    ],
    "status": [
        "Everything is running smoothly! All systems operational.",
        "Status: All good! What specific information would you like?",
        "All systems are functioning normally.",
    ],
    "thanks": [
        "You're welcome! Anything else I can help with?",
        "Happy to help! Let me know if you need anything else.",
        "My pleasure! Feel free to ask if you have more questions.",
    ],
    "question": [
        "That's a great question! Let me help you with that.",
        "I'll do my best to answer that for you.",
        "Good question! Here's what I can tell you...",
    ],
    "problem": [
        "I understand you're experiencing an issue. Let me help you troubleshoot.",
        "Sorry to hear you're having trouble. I'm here to help resolve this.",
        "Let me assist you with that problem right away.",
    ],
    "feedback": [
        "Thank you for your feedback! We really appreciate it.",
        "I value your input! Your feedback helps us improve.",
        "Thanks for sharing your thoughts!",
    ],
    "default": [
        "I'm processing your message. Could you please provide more details?",
        "Interesting! Tell me more about that.",
        "I'm here to help. Could you rephrase that for me?",
    ],
}


def lambda_handler(event, context):
    aws_request_id = getattr(context, "aws_request_id", None)
    batch_failures = []

    log_event(
        logger,
        logging.INFO,
        "nlp.batch_received",
        service=SERVICE_NAME,
        aws_request_id=aws_request_id,
        record_count=len(event.get("Records", [])),
    )

    for record in event.get("Records", []):
        correlation_id = extract_correlation_id(record)
        try:
            message_body = json.loads(record["body"])
            if correlation_id and "correlation_id" not in message_body:
                message_body["correlation_id"] = correlation_id
            process_message(message_body, sqs_message_id=record["messageId"])
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "nlp.record_failed",
                correlation_id=correlation_id,
                service=SERVICE_NAME,
                aws_request_id=aws_request_id,
                sqs_message_id=record.get("messageId"),
                error=str(exc),
                exc_info=True,
            )
            batch_failures.append({"itemIdentifier": record["messageId"]})

    if batch_failures:
        return {"batchItemFailures": batch_failures}

    return {"statusCode": 200, "body": json.dumps({"status": "processed"})}


def extract_correlation_id(record):
    attributes = record.get("messageAttributes") or {}
    attr = attributes.get("correlation_id") or {}
    if isinstance(attr, dict) and attr.get("stringValue"):
        return attr["stringValue"]
    try:
        body = json.loads(record.get("body") or "{}")
        return body.get("correlation_id")
    except json.JSONDecodeError:
        return None


def process_message(message_data, sqs_message_id=None):
    conversation_id = message_data["conversation_id"]
    user_id = message_data["user_id"]
    user_message = message_data["message"]
    channel = message_data["channel"]
    correlation_id = message_data.get("correlation_id")

    processing_key = build_processing_key(message_data, sqs_message_id)
    if not claim_processing_key(processing_key):
        log_event(
            logger,
            logging.INFO,
            "nlp.duplicate_skipped",
            correlation_id=correlation_id,
            service=SERVICE_NAME,
            processing_key=processing_key,
        )
        return

    intent = detect_intent(user_message)
    confidence = calculate_confidence(user_message, intent)
    bot_response = generate_response(intent, user_message)

    update_session(user_id, intent, channel)
    store_bot_response(conversation_id, bot_response, intent, confidence, correlation_id)
    log_analytics(conversation_id, user_id, intent, confidence, user_message, correlation_id)

    log_event(
        logger,
        logging.INFO,
        "nlp.processed",
        correlation_id=correlation_id,
        service=SERVICE_NAME,
        conversation_id=conversation_id,
        intent=intent,
        confidence=confidence,
    )


def build_processing_key(message_data, sqs_message_id):
    if sqs_message_id:
        return f"sqs:{sqs_message_id}"
    digest = hashlib.sha256(json.dumps(message_data, sort_keys=True).encode()).hexdigest()
    return f"msg:{digest}"


def detect_intent(message):
    message_lower = message.lower().strip()
    for intent, pattern in INTENTS.items():
        if re.search(pattern, message_lower, re.IGNORECASE):
            return intent
    return "default"


def calculate_confidence(message, intent):
    if intent == "default":
        return 0.3

    message_lower = message.lower()
    pattern = INTENTS.get(intent, "")
    matches = len(re.findall(pattern, message_lower, re.IGNORECASE))
    return round(min(0.5 + (matches * 0.2), 1.0), 2)


def generate_response(intent, user_message):
    response_list = RESPONSES.get(intent, RESPONSES["default"])
    base_response = random.choice(response_list)
    if intent == "question" and "?" in user_message:
        base_response += f"\n\nRegarding: '{user_message[:50]}...'"
    return base_response


def update_session(user_id, intent, channel):
    table = dynamodb.Table(SESSIONS_TABLE)
    current_time = int(datetime.now().timestamp())

    response = table.get_item(Key={"user_id": user_id})
    existing_item = response.get("Item", {})
    session_count = existing_item.get("session_count", 0) + 1
    intent_history = existing_item.get("intent_history", [])

    intent_history.append({"intent": intent, "timestamp": current_time})
    intent_history = intent_history[-10:]

    table.put_item(
        Item={
            "user_id": user_id,
            "last_intent": intent,
            "last_activity": current_time,
            "session_count": session_count,
            "channel": channel,
            "intent_history": intent_history,
            "ttl": current_time + (CONVERSATION_TTL_DAYS * 86400),
        }
    )


def store_bot_response(conversation_id, response, intent, confidence, correlation_id):
    table = dynamodb.Table(CONVERSATIONS_TABLE)
    timestamp = int(datetime.now().timestamp() * 1000)
    ttl = int(datetime.now().timestamp()) + (CONVERSATION_TTL_DAYS * 86400)

    table.put_item(
        Item={
            "conversation_id": conversation_id,
            "timestamp": timestamp,
            "message": response,
            "direction": "outbound",
            "intent": intent,
            "confidence": str(confidence),
            "correlation_id": correlation_id,
            "ttl": ttl,
        }
    )


def log_analytics(conversation_id, user_id, intent, confidence, message, correlation_id):
    log_event(
        logger,
        logging.INFO,
        "nlp.analytics",
        correlation_id=correlation_id,
        service=SERVICE_NAME,
        conversation_id=conversation_id,
        user_id=user_id,
        intent=intent,
        confidence=confidence,
        message_length=len(message),
        message_preview=message[:100],
    )
