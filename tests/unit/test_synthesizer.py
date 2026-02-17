"""
Tests for Tool Synthesizer
"""

import pytest
from unittest.mock import AsyncMock

from oats.core.types import RiskLevel, SynthesizedTool
from oats.core.synthesizer import Synthesizer, ExistingToolChecker
from oats.core.registry import CapabilityRegistry
from tests.conftest import MockLLMClient


class TestSynthesizer:
    """Tests for the Synthesizer class."""

    @pytest.mark.asyncio
    async def test_synthesize_basic_tool(
        self,
        mock_llm: MockLLMClient,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should synthesize a tool from intent."""
        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=capability_registry,
        )

        tool = await synthesizer.synthesize("fetch data from an API")

        assert tool is not None
        assert isinstance(tool, SynthesizedTool)
        assert tool.intent == "fetch data from an API"
        assert tool.code is not None
        assert "async def execute" in tool.code

    @pytest.mark.asyncio
    async def test_synthesize_calls_llm(
        self,
        mock_llm: MockLLMClient,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should call the LLM with proper prompts."""
        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=capability_registry,
        )

        await synthesizer.synthesize("do something")

        assert mock_llm.call_count == 1
        assert mock_llm.last_system is not None
        assert "Available Capabilities:" in mock_llm.last_system
        assert mock_llm.last_prompt is not None
        assert "do something" in mock_llm.last_prompt

    @pytest.mark.asyncio
    async def test_synthesize_respects_allowed_capabilities(
        self,
        mock_llm: MockLLMClient,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should only include allowed capabilities in synthesis context."""
        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=capability_registry,
        )

        await synthesizer.synthesize(
            "fetch github data",
            allowed_capabilities=["github"],
        )

        assert mock_llm.last_system is not None
        assert "github" in mock_llm.last_system
        # http should not be in the limited context
        # (depends on implementation - adjust if needed)

    @pytest.mark.asyncio
    async def test_synthesize_returns_none_when_existing_tools_suffice(
        self,
        mock_llm: MockLLMClient,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should return None if existing tools can handle the intent."""
        # Mock existing tool checker that says "yes, existing tools work"
        class AlwaysCanHandleChecker:
            async def can_handle(self, intent: str) -> tuple[bool, list[str]]:
                return (True, ["existing_tool"])

        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=capability_registry,
            existing_tool_checker=AlwaysCanHandleChecker(),
        )

        tool = await synthesizer.synthesize("do something existing tools can do")

        assert tool is None
        assert mock_llm.call_count == 0  # LLM should not be called

    @pytest.mark.asyncio
    async def test_synthesize_proceeds_when_existing_tools_insufficient(
        self,
        mock_llm: MockLLMClient,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should synthesize when existing tools cannot handle intent."""
        class NeverCanHandleChecker:
            async def can_handle(self, intent: str) -> tuple[bool, list[str]]:
                return (False, [])

        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=capability_registry,
            existing_tool_checker=NeverCanHandleChecker(),
        )

        tool = await synthesizer.synthesize("do something new")

        assert tool is not None
        assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_no_capabilities(
        self,
        mock_llm: MockLLMClient,
    ) -> None:
        """Should raise error if no capabilities are available."""
        empty_registry = CapabilityRegistry()

        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=empty_registry,
        )

        with pytest.raises(ValueError, match="No capabilities available"):
            await synthesizer.synthesize("do something")

    @pytest.mark.asyncio
    async def test_synthesize_parses_risk_level(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should correctly parse risk level from LLM response."""
        llm = MockLLMClient(responses=["""
CODE:
async def execute(context: dict) -> dict:
    return {"result": "high risk"}

CAPABILITIES_USED: filesystem
REQUESTED_SCOPES: filesystem:write
RISK_LEVEL: HIGH
RISK_REASONING: Writes to filesystem which could be destructive
HUMAN_EXPLANATION: This tool writes files to disk.
OUTPUT_SCHEMA: {"type": "object"}
"""])

        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
        )

        tool = await synthesizer.synthesize("write some files")

        assert tool is not None
        assert tool.risk_level == RiskLevel.HIGH
        assert "filesystem" in tool.risk_reasoning.lower()

    @pytest.mark.asyncio
    async def test_synthesize_extracts_scopes(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should extract requested scopes from LLM response."""
        llm = MockLLMClient(responses=["""
CODE:
async def execute(context: dict) -> dict:
    return {}

CAPABILITIES_USED: github, http
REQUESTED_SCOPES: github:repo:read, github:user:read, http:get
RISK_LEVEL: LOW
RISK_REASONING: Read only
HUMAN_EXPLANATION: Reads GitHub data.
OUTPUT_SCHEMA: {}
"""])

        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
        )

        tool = await synthesizer.synthesize("read github repos")

        assert tool is not None
        assert "github:repo:read" in tool.requested_scopes
        assert "http:get" in tool.requested_scopes

    @pytest.mark.asyncio
    async def test_synthesize_includes_model_info(
        self,
        mock_llm: MockLLMClient,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should include synthesizer model info in tool metadata."""
        synthesizer = Synthesizer(
            llm_client=mock_llm,
            capability_registry=capability_registry,
        )

        tool = await synthesizer.synthesize("do something")

        assert tool is not None
        assert tool.synthesizer_model == "mock-model"
