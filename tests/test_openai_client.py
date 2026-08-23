import json
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from ai_daily.llm.openai_client import OpenAIClient


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.request_kwargs = None

    async def create(self, **kwargs):
        self.request_kwargs = kwargs
        return self.response


def make_client(response):
    client = OpenAIClient.__new__(OpenAIClient)
    completions = FakeCompletions(response)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def completion_payload(*, with_usage=True):
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "兼容成功", "refusal": None},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
    }
    if with_usage:
        payload["usage"] = {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}
    return payload


@pytest.mark.asyncio
async def test_openai_client_parses_sdk_chat_completion_and_omits_empty_response_format():
    sdk_response = ChatCompletion.model_validate(completion_payload())
    client, completions = make_client(sdk_response)
    result = await client.generate("prompt", "test-model")
    assert result.text == "兼容成功"
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (3, 5, 8)
    assert "response_format" not in completions.request_kwargs
    assert completions.request_kwargs["stream"] is False


@pytest.mark.asyncio
async def test_openai_client_parses_dict_and_passes_actual_response_format():
    client, completions = make_client(completion_payload())
    result = await client.generate("prompt", "test-model", response_format={"type": "json_object"})
    assert result.text == "兼容成功"
    assert completions.request_kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_openai_client_parses_json_string_response():
    client, _ = make_client(json.dumps(completion_payload()))
    result = await client.generate("prompt", "test-model")
    assert result.text == "兼容成功"


@pytest.mark.asyncio
async def test_openai_client_parses_sse_string_response_from_compatible_gateway():
    sse_response = "\n\n".join(
        [
            'data: {"id":"chunk-1","object":"chat.completion.chunk","choices":[{"delta":{"content":"兼容"}}]}',
            'data: {"id":"chunk-2","object":"chat.completion.chunk","choices":[{"delta":{"content":"成功"}}],"usage":{"prompt_tokens":3,"completion_tokens":5,"total_tokens":8}}',
            "data: [DONE]",
        ]
    )
    client, _ = make_client(sse_response)
    result = await client.generate("prompt", "test-model")
    assert result.text == "兼容成功"
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (3, 5, 8)


@pytest.mark.asyncio
async def test_openai_client_rejects_html_string_with_safe_context():
    client, _ = make_client("<!doctype html><html><body>Gateway error</body></html>")
    with pytest.raises(RuntimeError, match="unexpected_response provider=openai response_type=str") as exc_info:
        await client.generate("prompt", "test-model")
    assert "html_response" in str(exc_info.value)
    assert "Gateway error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_client_rejects_missing_choices():
    client, _ = make_client({"usage": {"total_tokens": 1}})
    with pytest.raises(RuntimeError, match="missing_choices"):
        await client.generate("prompt", "test-model")


@pytest.mark.asyncio
async def test_openai_client_allows_missing_usage():
    client, _ = make_client(completion_payload(with_usage=False))
    result = await client.generate("prompt", "test-model")
    assert result.text == "兼容成功"
    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.total_tokens is None
