"""
Human-in-the-Loop Gate

ALL synthesized tools MUST pass through this gate before execution.
There is NO implicit trust - humans approve every tool.
"""

import time
from typing import Protocol, Any
from abc import ABC, abstractmethod

from oats.core.types import (
    SynthesizedTool,
    ApprovalRequest,
    ApprovalDecision,
    RiskLevel,
)


class ApprovalHandler(ABC):
    """
    Abstract handler for presenting approval requests to humans.

    Implementations can be CLI, GUI, web, Slack, etc.
    """

    @abstractmethod
    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """
        Present an approval request to a human and wait for decision.

        This method MUST block until a human makes a decision.
        There is no auto-approval.
        """
        ...

    @abstractmethod
    def format_for_display(self, request: ApprovalRequest) -> str:
        """
        Format the request for human-readable display.

        Returns a string that clearly shows:
        - What the tool intends to do
        - What capabilities/scopes it needs
        - The risk level and reasoning
        """
        ...


class CLIApprovalHandler(ApprovalHandler):
    """
    Simple CLI-based approval handler.

    For use in terminal environments.
    """

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Request approval via CLI input."""
        display = self.format_for_display(request)
        print(display)
        print()

        start_time = time.time()

        while True:
            response = input("Approve? [y/n/v(iew code)]: ").strip().lower()

            if response == "y":
                return ApprovalDecision(
                    approved=True,
                    decision_time_ms=int((time.time() - start_time) * 1000),
                )
            elif response == "n":
                reason = input("Reason for denial (optional): ").strip()
                return ApprovalDecision(
                    approved=False,
                    reason=reason,
                    decision_time_ms=int((time.time() - start_time) * 1000),
                )
            elif response == "v":
                print("\n--- CODE ---")
                print(request.tool.code)
                print("--- END CODE ---\n")
            else:
                print("Please enter 'y' (yes), 'n' (no), or 'v' (view code)")

    def format_for_display(self, request: ApprovalRequest) -> str:
        """Format for terminal display."""
        tool = request.tool
        risk_indicator = self._get_risk_indicator(tool.risk_level)

        lines = [
            "",
            "=" * 60,
            f"  Synth Tool Approval Request {risk_indicator}",
            "=" * 60,
            "",
            f"INTENT: {tool.intent}",
            "",
            f"EXPLANATION: {tool.human_explanation}",
            "",
            f"RISK LEVEL: {tool.risk_level.value}",
            f"RISK REASONING: {tool.risk_reasoning}",
            "",
            f"CAPABILITIES: {', '.join(tool.capabilities_used) or 'none'}",
            f"AUTH SCOPES: {', '.join(tool.requested_scopes) or 'none'}",
            "",
        ]

        if request.existing_tools_considered:
            lines.append(f"Existing tools considered: {', '.join(request.existing_tools_considered)}")
            lines.append(f"Why new tool needed: {request.why_new_tool_needed}")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def _get_risk_indicator(self, risk: RiskLevel) -> str:
        """Get a visual risk indicator."""
        indicators = {
            RiskLevel.LOW: "[LOW RISK]",
            RiskLevel.MEDIUM: "[MEDIUM RISK]",
            RiskLevel.HIGH: "[HIGH RISK]",
            RiskLevel.CRITICAL: "[!!! CRITICAL RISK !!!]",
        }
        return indicators.get(risk, "[UNKNOWN RISK]")


class HITLGate:
    """
    The main Human-in-the-Loop gate.

    ALL tools pass through here. No exceptions.
    No auto-approval. No YOLO mode.
    """

    def __init__(self, handler: ApprovalHandler) -> None:
        self.handler = handler
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    async def submit_for_approval(
        self,
        tool: SynthesizedTool,
        existing_tools_considered: list[str] | None = None,
        why_new_tool_needed: str = "",
    ) -> ApprovalDecision:
        """
        Submit a synthesized tool for human approval.

        This is the ONLY way to get approval. There are no shortcuts.

        Args:
            tool: The synthesized tool to approve
            existing_tools_considered: Tools that were checked but couldn't do the job
            why_new_tool_needed: Explanation of why synthesis was necessary

        Returns:
            ApprovalDecision from the human
        """
        request = ApprovalRequest(
            tool=tool,
            existing_tools_considered=existing_tools_considered or [],
            why_new_tool_needed=why_new_tool_needed,
        )

        self._pending_requests[tool.id] = request

        try:
            decision = await self.handler.request_approval(request)
            self._decisions[tool.id] = decision
            return decision
        finally:
            # Always clean up pending request
            self._pending_requests.pop(tool.id, None)

    def get_decision(self, tool_id: str) -> ApprovalDecision | None:
        """Get a previous decision by tool ID."""
        return self._decisions.get(tool_id)

    def was_approved(self, tool_id: str) -> bool:
        """Check if a tool was approved."""
        decision = self._decisions.get(tool_id)
        return decision.approved if decision else False

    def clear_history(self) -> None:
        """Clear decision history."""
        self._decisions.clear()


class CallbackApprovalHandler(ApprovalHandler):
    """
    Approval handler that uses a callback function.

    Useful for integrating with external approval systems.
    """

    def __init__(
        self,
        callback: Any,  # Callable[[ApprovalRequest], Awaitable[ApprovalDecision]]
        formatter: Any | None = None,  # Callable[[ApprovalRequest], str]
    ) -> None:
        self._callback = callback
        self._formatter = formatter

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Delegate to callback."""
        return await self._callback(request)

    def format_for_display(self, request: ApprovalRequest) -> str:
        """Use custom formatter or default."""
        if self._formatter:
            return self._formatter(request)

        # Default formatting
        tool = request.tool
        return f"""
Tool: {tool.id}
Intent: {tool.intent}
Risk: {tool.risk_level.value}
Scopes: {', '.join(tool.requested_scopes)}
"""
