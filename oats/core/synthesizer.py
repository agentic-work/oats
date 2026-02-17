"""
Tool Synthesizer

The core component that uses an LLM to generate one-shot tool code
based on user intent and available capabilities.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from oats.core.registry import CapabilityRegistry
from oats.core.types import (
    Capability,
    RiskLevel,
    SynthesizedTool,
)


class LLMClient(Protocol):
    """Protocol for LLM clients used by the synthesizer."""

    async def complete(
        self,
        system: str,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        """Generate a completion."""
        ...


class ExistingToolChecker(Protocol):
    """Protocol for checking if existing tools can handle the intent."""

    async def can_handle(self, intent: str) -> tuple[bool, list[str]]:
        """
        Check if existing tools can handle this intent.

        Returns:
            (can_handle, tool_names): Whether existing tools suffice and which ones.
        """
        ...


class Synthesizer:
    """
    Synthesizes one-shot tools from user intent.

    The synthesizer:
    1. Checks if existing tools can handle the intent (Synth shouldn't always synthesize)
    2. Analyzes the intent and available capabilities
    3. Generates executable code
    4. Self-assesses risk
    5. Produces a SynthesizedTool ready for HITL approval
    """

    def __init__(
        self,
        llm_client: LLMClient,
        capability_registry: CapabilityRegistry,
        existing_tool_checker: ExistingToolChecker | None = None,
    ) -> None:
        self.llm = llm_client
        self.capabilities = capability_registry
        self.existing_tool_checker = existing_tool_checker

    async def synthesize(
        self,
        intent: str,
        allowed_capabilities: list[str] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> SynthesizedTool | None:
        """
        Synthesize a tool from user intent.

        Args:
            intent: Natural language description of what the tool should do
            allowed_capabilities: Limit which capabilities can be used (None = all)
            constraints: Additional constraints (timeout, domains, etc.)

        Returns:
            SynthesizedTool if synthesis succeeded, None if existing tools suffice
        """
        # Step 1: Check if existing tools can handle this
        if self.existing_tool_checker:
            can_handle, tools = await self.existing_tool_checker.can_handle(intent)
            if can_handle:
                # Return None to signal: use existing tools instead
                return None

        # Step 2: Determine which capabilities to use
        available_caps = self._get_available_capabilities(allowed_capabilities)
        if not available_caps:
            raise ValueError("No capabilities available for synthesis")

        # Step 3: Generate the synthesis prompt
        system_prompt = self._build_system_prompt(available_caps, constraints)
        user_prompt = self._build_user_prompt(intent)

        # Step 4: Call the LLM
        response = await self.llm.complete(
            system=system_prompt,
            prompt=user_prompt,
        )

        # Step 5: Parse the response into a SynthesizedTool
        tool = self._parse_synthesis_response(response, intent, available_caps)

        return tool

    def _get_available_capabilities(
        self,
        allowed: list[str] | None,
    ) -> list[Capability]:
        """Get capabilities available for this synthesis."""
        all_caps = self.capabilities.get_all()

        if allowed is None:
            return all_caps

        return [cap for cap in all_caps if cap.name in allowed]

    def _build_system_prompt(
        self,
        capabilities: list[Capability],
        constraints: dict[str, Any] | None,
    ) -> str:
        """Build the system prompt for synthesis."""
        cap_context = "\n".join(
            f"- {cap.name}: {cap.description}"
            + (f" (auth: {cap.auth.type.value})" if cap.auth else "")
            for cap in capabilities
        )

        constraint_text = ""
        if constraints:
            constraint_text = "\n\nConstraints:\n" + "\n".join(
                f"- {k}: {v}" for k, v in constraints.items()
            )

        return f"""You are a tool synthesizer for the Synth (Tool Synthesis) framework.

Your job is to generate Python code that accomplishes a specific task using the available capabilities.

Available Capabilities:
{cap_context}
{constraint_text}

OUTPUT FORMAT:
You must respond with a structured output containing:
1. CODE: The Python async function to execute
2. CAPABILITIES_USED: List of capability names used
3. REQUESTED_SCOPES: Auth scopes needed
4. RISK_LEVEL: LOW, MEDIUM, HIGH, or CRITICAL
5. RISK_REASONING: Why this risk level
6. HUMAN_EXPLANATION: Plain English explanation (2-3 sentences)
7. OUTPUT_SCHEMA: JSON schema of expected output

RULES:
- Code must be a single async function named `execute`
- Code must handle errors gracefully
- Code must not hardcode credentials (use environment variables)
- Minimize scope requests - only request what's needed
- Be conservative with risk assessment

Example response format:
```
CODE:
async def execute(context: dict) -> dict:
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/data")
        return {{"data": response.json()}}

CAPABILITIES_USED: http
REQUESTED_SCOPES: http:get
RISK_LEVEL: LOW
RISK_REASONING: Read-only HTTP request to a known API endpoint
HUMAN_EXPLANATION: Fetches data from the example API. This is a read-only operation with no side effects.
OUTPUT_SCHEMA: {{"type": "object", "properties": {{"data": {{"type": "object"}}}}}}
```
"""

    def _build_user_prompt(self, intent: str) -> str:
        """Build the user prompt for synthesis."""
        return f"Synthesize a tool for the following intent:\n\n{intent}"

    def _parse_synthesis_response(
        self,
        response: str,
        intent: str,
        capabilities: list[Capability],
    ) -> SynthesizedTool:
        """Parse the LLM response into a SynthesizedTool."""
        # Parse structured sections from the response
        code = self._extract_section(response, "CODE:")
        caps_used = self._extract_list(response, "CAPABILITIES_USED:")
        scopes = self._extract_list(response, "REQUESTED_SCOPES:")
        risk_level_str = self._extract_section(response, "RISK_LEVEL:").strip().upper()
        risk_reasoning = self._extract_section(response, "RISK_REASONING:")
        human_explanation = self._extract_section(response, "HUMAN_EXPLANATION:")
        output_schema_str = self._extract_section(response, "OUTPUT_SCHEMA:")

        # Parse risk level
        try:
            risk_level = RiskLevel(risk_level_str)
        except ValueError:
            risk_level = RiskLevel.MEDIUM  # Default if parsing fails

        # Parse output schema
        import json
        try:
            output_schema = json.loads(output_schema_str) if output_schema_str else {}
        except json.JSONDecodeError:
            output_schema = {}

        return SynthesizedTool(
            id=str(uuid.uuid4()),
            intent=intent,
            code=code,
            language="python",
            requested_scopes=scopes,
            capabilities_used=caps_used,
            risk_level=risk_level,
            risk_reasoning=risk_reasoning,
            human_explanation=human_explanation,
            output_schema=output_schema,
            created_at=datetime.now(tz=UTC),
            synthesizer_model=getattr(self.llm, "model", "unknown"),
        )

    def _extract_section(self, text: str, marker: str) -> str:
        """Extract a section from the response starting at marker."""
        lines = text.split("\n")
        result = []
        capturing = False

        for line in lines:
            if marker in line:
                # Start capturing after the marker
                after_marker = line.split(marker, 1)[1].strip()
                if after_marker:
                    result.append(after_marker)
                capturing = True
            elif capturing:
                # Stop at next section marker
                if any(m in line for m in [
                    "CODE:", "CAPABILITIES_USED:", "REQUESTED_SCOPES:",
                    "RISK_LEVEL:", "RISK_REASONING:", "HUMAN_EXPLANATION:",
                    "OUTPUT_SCHEMA:"
                ]):
                    break
                result.append(line)

        return "\n".join(result).strip()

    def _extract_list(self, text: str, marker: str) -> list[str]:
        """Extract a comma-separated list from a section."""
        section = self._extract_section(text, marker)
        if not section:
            return []
        return [item.strip() for item in section.split(",") if item.strip()]
