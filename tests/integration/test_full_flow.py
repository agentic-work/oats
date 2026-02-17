"""
Integration tests for the full OAT flow:
Intent -> Synthesis -> HITL -> Execution -> Grounding
"""

import pytest

from oats.core.types import RiskLevel
from oats.core.registry import CapabilityRegistry
from oats.core.synthesizer import Synthesizer
from oats.core.executor import Executor, CredentialProvider
from oats.hitl.gate import HITLGate
from tests.conftest import MockLLMClient, MockApprovalHandler


class TestFullFlow:
    """Integration tests for complete OAT workflow."""

    @pytest.mark.asyncio
    async def test_synthesize_approve_execute_flow(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should complete full flow: synthesize -> approve -> execute."""
        # Setup
        llm = MockLLMClient(responses=["""
CODE:
async def execute(context: dict) -> dict:
    return {"answer": 42, "question": context.get("question", "unknown")}

CAPABILITIES_USED: none
REQUESTED_SCOPES: none
RISK_LEVEL: LOW
RISK_REASONING: Pure computation, no side effects
HUMAN_EXPLANATION: Returns the answer to everything.
OUTPUT_SCHEMA: {"type": "object", "properties": {"answer": {"type": "integer"}}}
"""])

        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
        )

        approval_handler = MockApprovalHandler(auto_approve=True)
        gate = HITLGate(handler=approval_handler)

        executor = Executor()

        # Flow
        # 1. Synthesize
        tool = await synthesizer.synthesize("what is the answer to everything?")
        assert tool is not None
        assert tool.risk_level == RiskLevel.LOW

        # 2. HITL Approval
        decision = await gate.submit_for_approval(tool)
        assert decision.approved is True

        # 3. Execute
        output = await executor.execute(
            tool,
            context={"question": "life, universe, everything"},
        )

        assert output.success is True
        assert output.result["answer"] == 42

    @pytest.mark.asyncio
    async def test_flow_stops_on_denial(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should not execute when HITL denies approval."""
        llm = MockLLMClient()
        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
        )

        denial_handler = MockApprovalHandler(auto_approve=False)
        gate = HITLGate(handler=denial_handler)

        executor = Executor()

        # Synthesize
        tool = await synthesizer.synthesize("do something risky")
        assert tool is not None

        # HITL denies
        decision = await gate.submit_for_approval(tool)
        assert decision.approved is False

        # Should NOT execute after denial
        # (In real implementation, caller checks decision before executing)
        assert not gate.was_approved(tool.id)

    @pytest.mark.asyncio
    async def test_flow_with_existing_tool_check(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should skip synthesis when existing tools can handle intent."""
        class SelectiveToolChecker:
            """Checker that knows about some existing tools."""
            KNOWN_INTENTS = {
                "read a file": ["read_file"],
                "list directory": ["list_dir"],
            }

            async def can_handle(self, intent: str) -> tuple[bool, list[str]]:
                for known, tools in self.KNOWN_INTENTS.items():
                    if known in intent.lower():
                        return (True, tools)
                return (False, [])

        llm = MockLLMClient()
        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
            existing_tool_checker=SelectiveToolChecker(),
        )

        # Intent that existing tools CAN handle
        tool = await synthesizer.synthesize("read a file from disk")
        assert tool is None  # No synthesis needed
        assert llm.call_count == 0

        # Intent that requires synthesis
        tool = await synthesizer.synthesize("fetch weather data from API")
        assert tool is not None
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_flow_with_credentials(
        self,
        capability_registry: CapabilityRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should properly inject credentials during execution."""
        monkeypatch.setenv("TEST_SECRET", "super_secret_value")

        llm = MockLLMClient(responses=["""
CODE:
async def execute(context: dict) -> dict:
    import os
    secret = os.environ.get("TEST_SECRET", "MISSING")
    return {"has_secret": secret == "super_secret_value"}

CAPABILITIES_USED: secure_api
REQUESTED_SCOPES: secure_api:read
RISK_LEVEL: MEDIUM
RISK_REASONING: Uses secret credentials
HUMAN_EXPLANATION: Accesses secure API with credentials.
OUTPUT_SCHEMA: {"type": "object"}
"""])

        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
        )

        approval_handler = MockApprovalHandler(auto_approve=True)
        gate = HITLGate(handler=approval_handler)

        creds = CredentialProvider()
        creds.register_credential("secure_api:read", "TEST_SECRET")
        executor = Executor(credential_provider=creds)

        # Full flow
        tool = await synthesizer.synthesize("access secure API")
        assert tool is not None

        decision = await gate.submit_for_approval(tool)
        assert decision.approved is True

        output = await executor.execute(tool)
        assert output.success is True
        assert output.result["has_secret"] is True

    @pytest.mark.asyncio
    async def test_flow_extracts_groundable_content(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should extract groundable content from execution results."""
        llm = MockLLMClient(responses=["""
CODE:
async def execute(context: dict) -> dict:
    return {
        "data": [
            {"name": "Alice", "score": 95},
            {"name": "Bob", "score": 87},
        ],
        "summary": "Two students with scores"
    }

CAPABILITIES_USED: none
REQUESTED_SCOPES: none
RISK_LEVEL: LOW
RISK_REASONING: Returns static data
HUMAN_EXPLANATION: Returns sample student data.
OUTPUT_SCHEMA: {"type": "object"}
"""])

        synthesizer = Synthesizer(
            llm_client=llm,
            capability_registry=capability_registry,
        )

        approval_handler = MockApprovalHandler(auto_approve=True)
        gate = HITLGate(handler=approval_handler)
        executor = Executor()

        tool = await synthesizer.synthesize("get student scores")
        await gate.submit_for_approval(tool)
        output = await executor.execute(tool)

        assert output.success is True
        assert output.groundable is not None
        assert "student" in output.groundable.embedding_text.lower()
        assert output.groundable.metadata["tool_id"] == tool.id
