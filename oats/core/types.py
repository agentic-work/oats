"""
Synth Core Types

Pydantic models for the On-demand Agent Tooling framework.
"""

from enum import Enum
from typing import Any, Callable, Awaitable
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk assessment levels for synthesized tools."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AuthType(str, Enum):
    """Authentication method types."""
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    OAUTH2 = "oauth2"
    BASIC = "basic"


class CapabilityAuth(BaseModel):
    """Authentication configuration for a capability."""
    type: AuthType
    scopes: list[str] = Field(default_factory=list)
    token_env_var: str | None = None  # Environment variable name for token
    description: str = ""

    model_config = {"extra": "forbid"}


class Capability(BaseModel):
    """
    A capability represents an available resource/API that tools can use.

    Unlike static tools, capabilities describe WHAT is available,
    not HOW to use it. The LLM synthesizes the HOW.
    """
    name: str = Field(..., description="Unique capability identifier")
    description: str = Field(..., description="Human-readable description")
    auth: CapabilityAuth | None = None

    # Constraints
    allowed_domains: list[str] = Field(default_factory=list)
    rate_limit: int | None = None  # Requests per minute
    max_response_size: int = 1_000_000  # 1MB default

    # Optional schema reference (OpenAPI, GraphQL, etc.)
    schema_url: str | None = None
    schema_type: str | None = None  # "openapi", "graphql", "custom"

    # SDK/client hints
    sdk_package: str | None = None  # e.g., "@slack/web-api"
    sdk_import: str | None = None   # e.g., "from slack_sdk import WebClient"

    model_config = {"extra": "forbid"}


class SynthesizedTool(BaseModel):
    """
    A tool synthesized by the LLM for one-shot execution.

    Contains everything needed to execute: code, auth requirements,
    risk assessment, and grounding strategy.
    """
    id: str = Field(..., description="Unique tool instance ID")
    intent: str = Field(..., description="Original user intent that triggered synthesis")

    # Generated code
    code: str = Field(..., description="Executable code (Python)")
    language: str = Field(default="python", description="Code language")

    # Execution requirements
    requested_scopes: list[str] = Field(default_factory=list)
    capabilities_used: list[str] = Field(default_factory=list)

    # Risk assessment
    risk_level: RiskLevel = Field(..., description="Self-assessed risk level")
    risk_reasoning: str = Field(..., description="Explanation of risk assessment")

    # For HITL display
    human_explanation: str = Field(..., description="Plain English explanation")

    # Output contract
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema of expected output"
    )

    # Grounding hints
    grounding_strategy: str = Field(
        default="extract_facts",
        description="How to ground the output for embeddings"
    )

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    synthesizer_model: str = Field(default="unknown")

    model_config = {"extra": "forbid"}


class ToolOutput(BaseModel):
    """Result from executing a synthesized tool."""
    tool_id: str
    success: bool

    # Raw output
    result: Any = None
    error: str | None = None

    # Execution metadata
    execution_time_ms: int = 0
    stdout: str = ""
    stderr: str = ""

    # For grounding
    groundable: "GroundableOutput | None" = None

    model_config = {"extra": "forbid"}


class GroundableOutput(BaseModel):
    """Structured output ready for embedding/grounding."""
    summary: str = Field(..., description="Human-readable summary")
    entities: list[dict[str, Any]] = Field(default_factory=list)
    embedding_text: str = Field(..., description="Text optimized for embedding")
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class ApprovalRequest(BaseModel):
    """Request sent to HITL gate for approval."""
    tool: SynthesizedTool

    # Context for the human
    existing_tools_considered: list[str] = Field(
        default_factory=list,
        description="Existing tools that were considered but insufficient"
    )
    why_new_tool_needed: str = Field(
        default="",
        description="Explanation of why synthesis is needed"
    )

    model_config = {"extra": "forbid"}


class ApprovalDecision(BaseModel):
    """Human's decision on an approval request."""
    approved: bool

    # Optional modifications
    modified_scopes: list[str] | None = None  # Restrict scopes
    modified_constraints: dict[str, Any] | None = None  # Add constraints

    # Feedback
    reason: str = ""

    # Timing
    decision_time_ms: int = 0

    model_config = {"extra": "forbid"}


# Type alias for approval callback
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalDecision]]
