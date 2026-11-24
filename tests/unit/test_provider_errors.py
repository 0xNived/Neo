import httpx

from neo.brain.providers import provider_error_reply


def test_provider_http_error_preserves_safe_details():
    request = httpx.Request(
        "POST",
        "https://api.example.test/chat/completions",
        headers={"Authorization": "Bearer gsk_should_never_be_shown"},
    )
    response = httpx.Response(
        429,
        request=request,
        headers={"x-request-id": "request-123", "retry-after": "7"},
        json={"error": {"message": "quota exhausted"}},
    )
    error = httpx.HTTPStatusError(
        "provider rejected request", request=request, response=response
    )

    reply = provider_error_reply(error)

    assert reply["kind"] == "message"
    assert "HTTP 429" in reply["content"]
    assert reply["diagnostic"]["status"] == 429
    assert reply["diagnostic"]["request_id"] == "request-123"
    assert reply["diagnostic"]["retry_after"] == "7"
    assert "quota exhausted" in reply["diagnostic"]["response_body"]
    assert "gsk_should_never_be_shown" not in str(reply)


def test_provider_parse_error_is_not_mislabeled_as_rate_limit():
    reply = provider_error_reply(KeyError("choices"), stage="response_parsing")

    assert "invalid response" in reply["content"]
    assert reply["diagnostic"]["stage"] == "response_parsing"
    assert reply["diagnostic"]["error_type"] == "KeyError"
