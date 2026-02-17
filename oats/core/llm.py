"""
LLM Client Adapters

Provides adapters for various LLM providers to work with the Synthesizer.
All clients implement a simple protocol: async complete(system, prompt) -> str
"""

import os
from typing import Any, Protocol

import httpx


class LLMClient(Protocol):
    """Protocol that all LLM clients must implement."""
    model: str

    async def complete(self, system: str, prompt: str, **kwargs: Any) -> str:
        """Generate a completion."""
        ...


class AnthropicClient:
    """
    Anthropic Claude client for tool synthesis.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )

        self.model = model
        self.max_tokens = max_tokens
        self.base_url = base_url

        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    async def complete(
        self,
        system: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """Generate a completion using Claude."""
        response = await self._client.messages.create(
            model=kwargs.get("model", self.model),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            system=system,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)

        return "\n".join(text_parts)


class OllamaClient:
    """
    Ollama client for local LLM inference.

    Uses the OpenAI-compatible API endpoint.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        max_tokens: int = 4096,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens

    async def complete(
        self,
        system: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """Generate a completion using Ollama."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": kwargs.get("model", self.model),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise ValueError(f"Ollama API error: {response.status_code} - {response.text}")

            data = response.json()
            return data["choices"][0]["message"]["content"]


class OpenAICompatibleClient:
    """
    Generic OpenAI-compatible API client.

    Works with any API that implements the OpenAI chat completions format,
    including:
    - OpenAI
    - Azure OpenAI
    - vLLM
    - LocalAI
    - Your custom endpoints
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str = "gpt-4",
        max_tokens: int = 4096,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.extra_headers = headers or {}

    async def complete(
        self,
        system: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """Generate a completion using OpenAI-compatible API."""
        headers = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json={
                    "model": kwargs.get("model", self.model),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise ValueError(f"API error: {response.status_code} - {response.text}")

            data = response.json()
            return data["choices"][0]["message"]["content"]


class AgenticWorkAPIClient:
    """
    Client for the AgenticWork platform API.

    Uses OpenAI-compatible chat completions format.
    Configure via environment variables:
      AGENTICWORK_API_URL  — platform base URL
      AGENTICWORK_API_KEY  — API key (awc_...)
      AGENTICWORK_MODEL    — model ID
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self.base_url = (base_url or os.environ.get("AGENTICWORK_API_URL", "")).rstrip("/")
        if not self.base_url:
            raise ValueError(
                "AgenticWork API URL required. Set AGENTICWORK_API_URL env var or pass base_url."
            )
        self.api_key = api_key or os.environ.get("AGENTICWORK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "AgenticWork API key required. Set AGENTICWORK_API_KEY env var or pass api_key."
            )
        self.model = model or os.environ.get("AGENTICWORK_MODEL", "")
        if not self.model:
            raise ValueError(
                "Model required. Set AGENTICWORK_MODEL env var or pass model."
            )
        self.max_tokens = max_tokens

    async def complete(
        self,
        system: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """Generate a completion using AgenticWork API."""
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            # AgenticWork API uses OpenAI-compatible format
            response = await client.post(
                f"{self.base_url}/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": kwargs.get("model", self.model),
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise ValueError(f"AgenticWork API error: {response.status_code} - {response.text}")

            data = response.json()
            return data["choices"][0]["message"]["content"]


class BedrockClient:
    """
    AWS Bedrock client for Claude models.

    Uses boto3 to call Bedrock's invoke_model API.
    Requires AWS credentials configured (via env vars, ~/.aws/credentials, or IAM role).
    """

    def __init__(
        self,
        model: str = "anthropic.claude-opus-4-6-v1",
        region: str = "us-east-1",
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.region = region
        self.max_tokens = max_tokens

        import boto3
        self._client = boto3.client("bedrock-runtime", region_name=region)

    async def complete(
        self,
        system: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """Generate a completion using Bedrock."""
        import asyncio
        import json

        model_id = kwargs.get("model", self.model)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        # Bedrock uses the Anthropic messages format
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [
                {"role": "user", "content": prompt}
            ],
        }

        # Run sync boto3 call in executor
        def invoke():
            response = self._client.invoke_model(
                modelId=model_id,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(response["body"].read())
            return response_body

        loop = asyncio.get_event_loop()
        response_body = await loop.run_in_executor(None, invoke)

        # Extract text from response
        text_parts = []
        for block in response_body.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        return "\n".join(text_parts)


class MockLLMClient:
    """Mock LLM client for testing without API calls."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or []
        self.call_count = 0
        self.last_system: str | None = None
        self.last_prompt: str | None = None
        self.model = "mock-model"

    async def complete(self, system: str, prompt: str, **kwargs: Any) -> str:
        self.last_system = system
        self.last_prompt = prompt
        self.call_count += 1

        if self.responses:
            return self.responses[min(self.call_count - 1, len(self.responses) - 1)]

        return """
CODE:
async def execute(context: dict) -> dict:
    return {"status": "ok", "message": "Mock execution"}

CAPABILITIES_USED: none
REQUESTED_SCOPES: none
RISK_LEVEL: LOW
RISK_REASONING: This is a mock tool with no real side effects
HUMAN_EXPLANATION: This mock tool returns a simple status message for testing.
OUTPUT_SCHEMA: {"type": "object", "properties": {"status": {"type": "string"}}}
"""


def create_llm_client(
    provider: str = "anthropic",
    **kwargs: Any,
) -> LLMClient:
    """
    Factory function to create an LLM client.

    Args:
        provider: One of "anthropic", "ollama", "openai", "agenticwork", "mock"
        **kwargs: Provider-specific configuration

    Examples:
        # Anthropic (default)
        client = create_llm_client("anthropic", api_key="sk-...")

        # Ollama on local machine
        client = create_llm_client("ollama", model="llama3.2")

        # Ollama on remote server (hal)
        client = create_llm_client("ollama", base_url="http://hal:11434", model="qwen2.5:32b")

        # AgenticWork API
        client = create_llm_client("agenticwork", api_key="...")

        # Generic OpenAI-compatible
        client = create_llm_client("openai", base_url="https://api.openai.com", api_key="sk-...")

        # Custom endpoint
        client = create_llm_client("openai", base_url="https://your-api.com", api_key="...")
    """
    providers = {
        "anthropic": AnthropicClient,
        "bedrock": BedrockClient,
        "ollama": OllamaClient,
        "openai": OpenAICompatibleClient,
        "agenticwork": AgenticWorkAPIClient,
        "mock": MockLLMClient,
    }

    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(providers.keys())}")

    return providers[provider](**kwargs)
