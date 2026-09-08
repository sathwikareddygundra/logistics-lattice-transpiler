import httpx
import pytest
import respx

from common.groq_client import (
    GROQ_API_BASE_URL,
    MAX_RETRIES,
    GroqClient,
    GroqClientError,
)


@pytest.fixture(autouse=True)
def groq_api_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # Don't actually wait out the backoff delay during tests.
    monkeypatch.setattr("common.groq_client.time.sleep", lambda _: None)


@respx.mock
def test_succeeds_immediately_on_200():
    route = respx.post(f"{GROQ_API_BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
    )
    client = GroqClient()
    result = client.chat_completion("some-model", [{"role": "user", "content": "hello"}])
    assert result.content == "hi"
    assert route.call_count == 1


@respx.mock
def test_retries_on_429_then_succeeds():
    route = respx.post(f"{GROQ_API_BASE_URL}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json={"choices": [{"message": {"content": "recovered"}}]}),
        ]
    )
    client = GroqClient()
    result = client.chat_completion("some-model", [{"role": "user", "content": "hello"}])
    assert result.content == "recovered"
    assert route.call_count == 2


@respx.mock
def test_retries_on_500_then_succeeds():
    route = respx.post(f"{GROQ_API_BASE_URL}/chat/completions").mock(
        side_effect=[
            httpx.Response(500, json={"error": "server error"}),
            httpx.Response(200, json={"choices": [{"message": {"content": "recovered"}}]}),
        ]
    )
    client = GroqClient()
    result = client.chat_completion("some-model", [{"role": "user", "content": "hello"}])
    assert result.content == "recovered"
    assert route.call_count == 2


@respx.mock
def test_raises_after_exhausting_retries():
    route = respx.post(f"{GROQ_API_BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "still down"})
    )
    client = GroqClient()
    with pytest.raises(GroqClientError):
        client.chat_completion("some-model", [{"role": "user", "content": "hello"}])
    assert route.call_count == MAX_RETRIES + 1


@respx.mock
def test_non_retryable_error_fails_immediately():
    route = respx.post(f"{GROQ_API_BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": "bad request"})
    )
    client = GroqClient()
    with pytest.raises(GroqClientError):
        client.chat_completion("some-model", [{"role": "user", "content": "hello"}])
    assert route.call_count == 1


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(GroqClientError):
        GroqClient(api_key=None)
