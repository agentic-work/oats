"""
Pytest configuration and fixtures for OAT tests.
"""

import pytest
from typing import Any

from oats.core.types import (
    Capability,
    CapabilityAuth,
    AuthType,
    SynthesizedTool,
    RiskLevel,
    ApprovalRequest,
    ApprovalDecision,
)
from oats.core.registry import CapabilityRegistry
from oats.hitl.gate import ApprovalHandler


# ============================================
# Mock LLM Client
# ============================================

class MockLLMClient:
    """Mock LLM client for testing."""

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

        # Default response with all required fields
        return """
CODE:
async def execute(context: dict) -> dict:
    return {"status": "ok", "message": "Mock execution"}

CAPABILITIES_USED: http
REQUESTED_SCOPES: http:get
RISK_LEVEL: LOW
RISK_REASONING: This is a mock tool with no real side effects
HUMAN_EXPLANATION: This mock tool returns a simple status message for testing.
OUTPUT_SCHEMA: {"type": "object", "properties": {"status": {"type": "string"}}}
"""


@pytest.fixture
def mock_llm() -> MockLLMClient:
    """Provide a mock LLM client."""
    return MockLLMClient()


# ============================================
# Mock Approval Handler
# ============================================

class MockApprovalHandler(ApprovalHandler):
    """Mock approval handler that auto-approves or auto-denies."""

    def __init__(self, auto_approve: bool = True) -> None:
        self.auto_approve = auto_approve
        self.requests: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        return ApprovalDecision(
            approved=self.auto_approve,
            reason="Mock decision" if not self.auto_approve else "",
        )

    def format_for_display(self, request: ApprovalRequest) -> str:
        return f"Mock display: {request.tool.intent}"


@pytest.fixture
def mock_approval_handler() -> MockApprovalHandler:
    """Provide a mock approval handler that auto-approves."""
    return MockApprovalHandler(auto_approve=True)


@pytest.fixture
def mock_denial_handler() -> MockApprovalHandler:
    """Provide a mock approval handler that auto-denies."""
    return MockApprovalHandler(auto_approve=False)


# ============================================
# Sample Capabilities
# ============================================

@pytest.fixture
def http_capability() -> Capability:
    """HTTP capability for testing."""
    return Capability(
        name="http",
        description="Make HTTP requests",
        auth=CapabilityAuth(
            type=AuthType.NONE,
            description="No auth required",
        ),
        allowed_domains=["api.example.com", "httpbin.org"],
    )


@pytest.fixture
def github_capability() -> Capability:
    """GitHub capability for testing."""
    return Capability(
        name="github",
        description="Access GitHub API",
        auth=CapabilityAuth(
            type=AuthType.BEARER,
            scopes=["repo:read", "repo:write", "user:read"],
            token_env_var="GITHUB_TOKEN",
            description="GitHub Personal Access Token",
        ),
        allowed_domains=["api.github.com"],
        sdk_import="from github import Github",
    )


@pytest.fixture
def filesystem_capability() -> Capability:
    """Filesystem capability for testing."""
    return Capability(
        name="filesystem",
        description="Read/write local files",
        auth=CapabilityAuth(
            type=AuthType.NONE,
        ),
    )


@pytest.fixture
def capability_registry(
    http_capability: Capability,
    github_capability: Capability,
    filesystem_capability: Capability,
) -> CapabilityRegistry:
    """Pre-populated capability registry."""
    registry = CapabilityRegistry()
    registry.register(http_capability)
    registry.register(github_capability)
    registry.register(filesystem_capability)
    return registry


# ============================================
# Sample Synthesized Tool
# ============================================

@pytest.fixture
def sample_tool() -> SynthesizedTool:
    """Sample synthesized tool for testing."""
    return SynthesizedTool(
        id="test-tool-123",
        intent="fetch current time from API",
        code="""
async def execute(context: dict) -> dict:
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get("https://httpbin.org/get")
        return {"status": response.status_code}
""",
        language="python",
        requested_scopes=["http:get"],
        capabilities_used=["http"],
        risk_level=RiskLevel.LOW,
        risk_reasoning="Read-only HTTP request",
        human_explanation="Fetches data from httpbin.org",
        output_schema={"type": "object", "properties": {"status": {"type": "integer"}}},
    )


@pytest.fixture
def dangerous_tool() -> SynthesizedTool:
    """Tool with dangerous code for testing validation."""
    return SynthesizedTool(
        id="dangerous-tool-456",
        intent="do something risky",
        code="""
async def execute(context: dict) -> dict:
    import os
    os.system("rm -rf /")  # DANGEROUS!
    return {"status": "done"}
""",
        language="python",
        requested_scopes=["filesystem:write"],
        capabilities_used=["filesystem"],
        risk_level=RiskLevel.CRITICAL,
        risk_reasoning="Destructive system command",
        human_explanation="This tool attempts to delete system files",
        output_schema={},
    )
