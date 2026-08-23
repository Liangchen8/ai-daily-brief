import pytest

from ai_daily.llm.base import LLMResponse
from ai_daily.llm.router import ModelRouter


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def generate(self, prompt, model, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response or LLMResponse(text="{}", provider="fake", model=model)


class SequenceClient:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0
        self.prompts = []

    async def generate(self, prompt, model, **kwargs):
        self.calls += 1
        self.prompts.append(prompt)
        return LLMResponse(text=self.texts.pop(0), provider="openai", model=model)


class ResponseFormatFallbackClient:
    def __init__(self):
        self.calls = []

    async def generate(self, prompt, model, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("unexpected_response provider=openai response_type=str reason=missing_sse_content")
        return LLMResponse(text='{"results": []}', provider="openai", model=model)


@pytest.mark.asyncio
async def test_primary_success_does_not_call_fallback(app_config):
    app_config.environ.update({"FILTER_PROVIDER": "openai", "FILTER_MODEL": "primary"})
    primary = FakeClient(LLMResponse(text="ok", provider="openai", model="primary"))
    fallback = FakeClient(LLMResponse(text="fallback", provider="deepseek", model="fallback"))
    router = ModelRouter(app_config, clients={"openai": primary, "deepseek": fallback})
    result = await router.generate("filter", "prompt")
    assert result.text == "ok"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_timeout_retries_then_fallback(app_config):
    app_config.environ.update({"FILTER_PROVIDER": "openai", "FILTER_MODEL": "primary"})
    app_config.models["filter"]["fallback"]["provider"] = "deepseek"
    app_config.models["filter"]["fallback"]["model"] = "fallback"
    primary = FakeClient(error=TimeoutError())
    fallback = FakeClient(LLMResponse(text="fallback", provider="deepseek", model="fallback"))
    router = ModelRouter(app_config, clients={"openai": primary, "deepseek": fallback})
    result = await router.generate("filter", "prompt")
    assert result.text == "fallback"
    assert primary.calls == 3
    assert fallback.calls == 1
    assert router.usage[0].fallback_used is True


@pytest.mark.asyncio
async def test_unknown_provider_is_reported(app_config):
    app_config.environ.update({"FILTER_PROVIDER": "unknown", "FILTER_MODEL": "x"})
    router = ModelRouter(app_config, clients={})
    with pytest.raises(ValueError, match="不支持的 Provider"):
        await router.generate("filter", "prompt")


@pytest.mark.asyncio
async def test_structured_output_has_one_repair_attempt(app_config):
    app_config.environ.update({"FILTER_PROVIDER": "openai", "FILTER_MODEL": "primary"})
    client = SequenceClient(["not-json", '{"results": []}'])
    router = ModelRouter(app_config, clients={"openai": client})
    from ai_daily.llm.classifier import BatchClassification
    result = await router.generate_structured("filter", "prompt", BatchClassification)
    assert result.results == []
    assert client.calls == 2
    assert "JSON Schema" in client.prompts[0]
    assert "BatchClassification" in client.prompts[0]


@pytest.mark.asyncio
async def test_structured_output_retries_without_response_format_for_sse_gateway(app_config):
    app_config.environ.update({"FILTER_PROVIDER": "openai", "FILTER_MODEL": "primary"})
    client = ResponseFormatFallbackClient()
    router = ModelRouter(app_config, clients={"openai": client})
    from ai_daily.llm.classifier import BatchClassification
    result = await router.generate_structured("filter", "prompt", BatchClassification)
    assert result.results == []
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in client.calls[1]
