import json

import nlp_processor


def test_detect_intent_greeting():
    assert nlp_processor.detect_intent("Hello there") == "greeting"


def test_detect_intent_default():
    assert nlp_processor.detect_intent("asdfghjkl") == "default"


def test_calculate_confidence_default():
    assert nlp_processor.calculate_confidence("unknown", "default") == 0.3


def test_lambda_handler_reports_batch_failures(monkeypatch):
    def boom(_message_data, sqs_message_id=None):
        raise RuntimeError("processing failed")

    monkeypatch.setattr(nlp_processor, "process_message", boom)

    event = {
        "Records": [
            {"messageId": "msg-1", "body": json.dumps({"conversation_id": "c1", "user_id": "u1", "message": "hi", "channel": "web"})},
            {"messageId": "msg-2", "body": json.dumps({"conversation_id": "c2", "user_id": "u2", "message": "bye", "channel": "web"})},
        ]
    }

    result = nlp_processor.lambda_handler(event, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-1"}, {"itemIdentifier": "msg-2"}]}
