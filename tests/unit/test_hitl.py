"""
Tests for Human-in-the-Loop Gate
"""

import pytest

from oats.core.types import (
    SynthesizedTool,
    RiskLevel,
    ApprovalRequest,
    ApprovalDecision,
)
from oats.hitl.gate import HITLGate, CLIApprovalHandler, CallbackApprovalHandler
from tests.conftest import MockApprovalHandler


class TestHITLGate:
    """Tests for the HITLGate class."""

    @pytest.mark.asyncio
    async def test_submit_for_approval_approved(
        self,
        sample_tool: SynthesizedTool,
        mock_approval_handler: MockApprovalHandler,
    ) -> None:
        """Should return approved decision when handler approves."""
        gate = HITLGate(handler=mock_approval_handler)

        decision = await gate.submit_for_approval(sample_tool)

        assert decision.approved is True
        assert len(mock_approval_handler.requests) == 1

    @pytest.mark.asyncio
    async def test_submit_for_approval_denied(
        self,
        sample_tool: SynthesizedTool,
        mock_denial_handler: MockApprovalHandler,
    ) -> None:
        """Should return denied decision when handler denies."""
        gate = HITLGate(handler=mock_denial_handler)

        decision = await gate.submit_for_approval(sample_tool)

        assert decision.approved is False
        assert decision.reason == "Mock decision"

    @pytest.mark.asyncio
    async def test_submit_includes_context(
        self,
        sample_tool: SynthesizedTool,
        mock_approval_handler: MockApprovalHandler,
    ) -> None:
        """Should include context about existing tools considered."""
        gate = HITLGate(handler=mock_approval_handler)

        await gate.submit_for_approval(
            sample_tool,
            existing_tools_considered=["read_file", "http_get"],
            why_new_tool_needed="Need to combine API call with transformation",
        )

        request = mock_approval_handler.requests[0]
        assert "read_file" in request.existing_tools_considered
        assert "http_get" in request.existing_tools_considered
        assert "transformation" in request.why_new_tool_needed

    @pytest.mark.asyncio
    async def test_get_decision(
        self,
        sample_tool: SynthesizedTool,
        mock_approval_handler: MockApprovalHandler,
    ) -> None:
        """Should retrieve previous decisions."""
        gate = HITLGate(handler=mock_approval_handler)

        await gate.submit_for_approval(sample_tool)
        decision = gate.get_decision(sample_tool.id)

        assert decision is not None
        assert decision.approved is True

    @pytest.mark.asyncio
    async def test_was_approved(
        self,
        sample_tool: SynthesizedTool,
        mock_approval_handler: MockApprovalHandler,
    ) -> None:
        """Should check if tool was approved."""
        gate = HITLGate(handler=mock_approval_handler)

        # Before approval
        assert gate.was_approved(sample_tool.id) is False

        await gate.submit_for_approval(sample_tool)

        # After approval
        assert gate.was_approved(sample_tool.id) is True

    @pytest.mark.asyncio
    async def test_clear_history(
        self,
        sample_tool: SynthesizedTool,
        mock_approval_handler: MockApprovalHandler,
    ) -> None:
        """Should clear decision history."""
        gate = HITLGate(handler=mock_approval_handler)

        await gate.submit_for_approval(sample_tool)
        assert gate.was_approved(sample_tool.id) is True

        gate.clear_history()
        assert gate.was_approved(sample_tool.id) is False


class TestCallbackApprovalHandler:
    """Tests for the CallbackApprovalHandler class."""

    @pytest.mark.asyncio
    async def test_callback_is_called(
        self,
        sample_tool: SynthesizedTool,
    ) -> None:
        """Should call the provided callback."""
        calls: list[ApprovalRequest] = []

        async def mock_callback(request: ApprovalRequest) -> ApprovalDecision:
            calls.append(request)
            return ApprovalDecision(approved=True)

        handler = CallbackApprovalHandler(callback=mock_callback)
        request = ApprovalRequest(tool=sample_tool)

        decision = await handler.request_approval(request)

        assert len(calls) == 1
        assert decision.approved is True

    @pytest.mark.asyncio
    async def test_custom_formatter(
        self,
        sample_tool: SynthesizedTool,
    ) -> None:
        """Should use custom formatter when provided."""
        async def mock_callback(request: ApprovalRequest) -> ApprovalDecision:
            return ApprovalDecision(approved=True)

        def custom_formatter(request: ApprovalRequest) -> str:
            return f"CUSTOM: {request.tool.intent}"

        handler = CallbackApprovalHandler(
            callback=mock_callback,
            formatter=custom_formatter,
        )
        request = ApprovalRequest(tool=sample_tool)

        display = handler.format_for_display(request)

        assert display.startswith("CUSTOM:")
        assert sample_tool.intent in display


class TestCLIApprovalHandler:
    """Tests for CLIApprovalHandler formatting."""

    def test_format_for_display_low_risk(
        self,
        sample_tool: SynthesizedTool,
    ) -> None:
        """Should format low-risk tools appropriately."""
        handler = CLIApprovalHandler()
        request = ApprovalRequest(tool=sample_tool)

        display = handler.format_for_display(request)

        assert "OAT Tool Approval Request" in display
        assert sample_tool.intent in display
        assert "LOW" in display

    def test_format_for_display_critical_risk(
        self,
        dangerous_tool: SynthesizedTool,
    ) -> None:
        """Should highlight critical-risk tools."""
        handler = CLIApprovalHandler()
        request = ApprovalRequest(tool=dangerous_tool)

        display = handler.format_for_display(request)

        assert "CRITICAL" in display
        assert "!!!" in display  # Visual warning

    def test_format_includes_scopes(
        self,
        sample_tool: SynthesizedTool,
    ) -> None:
        """Should include requested scopes in display."""
        handler = CLIApprovalHandler()
        request = ApprovalRequest(tool=sample_tool)

        display = handler.format_for_display(request)

        assert "AUTH SCOPES:" in display

    def test_format_includes_capabilities(
        self,
        sample_tool: SynthesizedTool,
    ) -> None:
        """Should include used capabilities in display."""
        handler = CLIApprovalHandler()
        request = ApprovalRequest(tool=sample_tool)

        display = handler.format_for_display(request)

        assert "CAPABILITIES:" in display


class TestApprovalDecision:
    """Tests for ApprovalDecision model."""

    def test_approved_decision(self) -> None:
        """Should create approved decision."""
        decision = ApprovalDecision(approved=True)

        assert decision.approved is True
        assert decision.reason == ""

    def test_denied_with_reason(self) -> None:
        """Should create denied decision with reason."""
        decision = ApprovalDecision(
            approved=False,
            reason="Too risky for production",
        )

        assert decision.approved is False
        assert "risky" in decision.reason

    def test_modified_scopes(self) -> None:
        """Should allow scope modifications."""
        decision = ApprovalDecision(
            approved=True,
            modified_scopes=["read_only"],  # Restricted from original
        )

        assert decision.approved is True
        assert decision.modified_scopes == ["read_only"]


class TestApprovalRequest:
    """Tests for ApprovalRequest model."""

    def test_basic_request(self, sample_tool: SynthesizedTool) -> None:
        """Should create basic approval request."""
        request = ApprovalRequest(tool=sample_tool)

        assert request.tool == sample_tool
        assert request.existing_tools_considered == []

    def test_request_with_context(self, sample_tool: SynthesizedTool) -> None:
        """Should include context about tool selection."""
        request = ApprovalRequest(
            tool=sample_tool,
            existing_tools_considered=["http_get", "file_read"],
            why_new_tool_needed="Need to combine multiple operations",
        )

        assert "http_get" in request.existing_tools_considered
        assert "combine" in request.why_new_tool_needed
