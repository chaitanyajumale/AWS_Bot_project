from bot_common.validation import validate_message_request


def test_valid_web_payload():
    payload, errors = validate_message_request(
        {"message": "Hello", "user_id": "user-1", "channel": "web"}
    )
    assert errors == []
    assert payload == {"channel": "web", "user_id": "user-1", "message": "Hello"}


def test_missing_message_rejected():
    _, errors = validate_message_request({"user_id": "user-1", "channel": "web"})
    assert "message is required and must be non-empty" in errors


def test_unsupported_channel_rejected():
    _, errors = validate_message_request(
        {"message": "Hi", "user_id": "user-1", "channel": "sms"}
    )
    assert any("channel must be one of" in err for err in errors)


def test_message_length_capped():
    payload, errors = validate_message_request(
        {"message": "x" * 5000, "user_id": "user-1", "channel": "web"}
    )
    assert errors == []
    assert payload is not None
    assert len(payload["message"]) == 4000
