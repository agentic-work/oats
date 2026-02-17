"""
AgenticWork Platform Integration for Synth (Tool Synthesis)

When a user logs into AgenticWork via Azure SSO or Google SSO:
1. Platform authenticates user and gets OAuth tokens
2. Platform calls Synth with user's credentials
3. Synth executes tools AS that user
4. All actions are logged with user identity

Architecture:
┌─────────────────────────────────────────────────────────────────────┐
│                     AgenticWork Platform                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐ │
│  │ Azure SSO   │    │ Google SSO  │    │  User Token Store       │ │
│  │ (OAuth 2.0) │    │ (OAuth 2.0) │    │  - Access tokens        │ │
│  └──────┬──────┘    └──────┬──────┘    │  - Refresh tokens       │ │
│         │                  │           │  - Cloud credentials    │ │
│         └────────┬─────────┘           └───────────┬─────────────┘ │
│                  │                                 │               │
│                  ▼                                 ▼               │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    Synth Framework                              │ │
│  │  ┌─────────────────────────────────────────────────────────┐  │ │
│  │  │ PlatformSynthClient                                     │  │ │
│  │  │  - Receives user tokens from platform                   │  │ │
│  │  │  - Injects credentials into execution environment       │  │ │
│  │  │  - Logs all actions with user identity                  │  │ │
│  │  │  - Reports usage/cost back to platform                  │  │ │
│  │  └─────────────────────────────────────────────────────────┘  │ │
│  │                          │                                     │ │
│  │                          ▼                                     │ │
│  │  ┌─────────────────────────────────────────────────────────┐  │ │
│  │  │ Sandboxed Execution (runs AS user)                      │  │ │
│  │  │  - AWS calls use user's credentials                     │  │ │
│  │  │  - Azure calls use user's OAuth token                   │  │ │
│  │  │  - GCP calls use user's OAuth token                     │  │ │
│  │  └─────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
"""

import os
from dataclasses import dataclass
from typing import Any, Callable
from pathlib import Path

from oats.core.synthesizer import Synthesizer
from oats.core.executor import Executor, SandboxConfig, CredentialProvider
from oats.core.llm import create_llm_client
from oats.core.identity import PlatformCredentialInjector, UserIdentity
from oats.core.metrics import (
    MetricsCollector,
    SynthesisMetrics,
    TokenUsage,
    get_metrics_collector,
)
from oats.core.types import SynthesizedTool, ToolOutput, RiskLevel
from oats.capabilities import load_builtin_capabilities
from oats.hitl.gate import HITLGate, ApprovalHandler, ApprovalRequest, ApprovalDecision


@dataclass
class PlatformUser:
    """User authenticated via platform SSO."""
    user_id: str
    email: str
    display_name: str
    provider: str  # "azure" or "google"
    tenant_id: str | None = None  # Azure tenant

    # OAuth tokens (obtained via SSO)
    access_token: str | None = None
    refresh_token: str | None = None
    token_expiry: float | None = None

    # Cloud credentials (if user has linked accounts)
    aws_credentials: dict | None = None  # access_key_id, secret_access_key, session_token
    azure_credentials: dict | None = None  # access_token, tenant_id
    gcp_credentials: dict | None = None  # access_token, project_id


@dataclass
class ExecutionResult:
    """Result of an Synth execution in platform context."""
    success: bool
    tool_id: str
    result: Any
    metrics: SynthesisMetrics
    error: str | None = None


class PlatformSynthClient:
    """
    Synth client for AgenticWork platform integration.

    Handles:
    - User credential injection from SSO
    - Execution as the authenticated user
    - Metrics and logging with user identity
    - Usage reporting for billing
    """

    def __init__(
        self,
        llm_provider: str = "bedrock",
        llm_model: str = "us.anthropic.claude-opus-4-6-v1",
        log_file: Path | None = None,
        on_usage_report: Callable[[SynthesisMetrics], None] | None = None,
    ):
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.on_usage_report = on_usage_report

        self.registry = load_builtin_capabilities()
        self.llm_client = create_llm_client(
            provider=llm_provider,
            model=llm_model,
        )
        self.synthesizer = Synthesizer(
            llm_client=self.llm_client,
            capability_registry=self.registry,
        )
        self.credential_injector = PlatformCredentialInjector()
        self.metrics = MetricsCollector(
            log_file=log_file,
            emit_to_stdout=bool(os.environ.get("SYNTH_DEBUG")),
        )

    async def synthesize_and_execute(
        self,
        intent: str,
        user: PlatformUser,
        auto_approve_low_risk: bool = False,
        approval_callback: Callable[[ApprovalRequest], ApprovalDecision] | None = None,
    ) -> ExecutionResult:
        """
        Synthesize and execute a tool for a platform user.

        The tool runs AS the user using their SSO credentials.
        All actions are logged with user identity.
        """
        # Start metrics tracking
        metrics = self.metrics.start_synthesis(
            tool_id="pending",
            intent=intent,
            provider=self.llm_provider,
            model=self.llm_model,
            user_identity={
                "user_id": user.user_id,
                "email": user.email,
                "provider": user.provider,
            },
        )

        try:
            # Step 1: Synthesize the tool
            tool = await self.synthesizer.synthesize(intent)

            if tool is None:
                return ExecutionResult(
                    success=True,
                    tool_id="none",
                    result={"message": "Existing tools can handle this intent"},
                    metrics=metrics,
                )

            metrics.tool_id = tool.id

            # Record synthesis metrics (would need token counting from LLM)
            self.metrics.record_synthesis_complete(
                metrics,
                tokens=TokenUsage(input_tokens=0, output_tokens=0),  # TODO: Get from LLM
                risk_level=tool.risk_level,
                capabilities=tool.capabilities_used,
            )

            # Step 2: Approval
            if tool.risk_level == RiskLevel.LOW and auto_approve_low_risk:
                approved = True
            elif approval_callback:
                request = ApprovalRequest(tool=tool)
                decision = approval_callback(request)
                approved = decision.approved
                self.metrics.record_approval(metrics, approved, decision.reason)
            else:
                # No approval callback and not auto-approved
                return ExecutionResult(
                    success=False,
                    tool_id=tool.id,
                    result=None,
                    metrics=metrics,
                    error="Approval required but no approval callback provided",
                )

            if not approved:
                return ExecutionResult(
                    success=False,
                    tool_id=tool.id,
                    result=None,
                    metrics=metrics,
                    error="User denied approval",
                )

            # Step 3: Execute as user
            output = await self._execute_as_user(tool, user)

            self.metrics.record_execution_complete(
                metrics,
                success=output.success,
                execution_time_ms=output.execution_time_ms,
                error=output.error,
            )

            # Report usage for billing
            if self.on_usage_report:
                self.on_usage_report(metrics)

            return ExecutionResult(
                success=output.success,
                tool_id=tool.id,
                result=output.result,
                metrics=metrics,
                error=output.error,
            )

        except Exception as e:
            self.metrics.record_synthesis_failed(metrics, str(e))
            return ExecutionResult(
                success=False,
                tool_id=metrics.tool_id,
                result=None,
                metrics=metrics,
                error=str(e),
            )

    async def _execute_as_user(
        self,
        tool: SynthesizedTool,
        user: PlatformUser,
    ) -> ToolOutput:
        """Execute tool with user's credentials injected."""
        # Build credential environment from user's tokens
        cred_env = {}

        # Inject AWS credentials if available
        if user.aws_credentials:
            cred_env.update(self.credential_injector.inject_aws_credentials(
                access_key_id=user.aws_credentials["access_key_id"],
                secret_access_key=user.aws_credentials["secret_access_key"],
                session_token=user.aws_credentials.get("session_token"),
            ))

        # Inject Azure credentials if available
        if user.azure_credentials:
            cred_env.update(self.credential_injector.inject_azure_token(
                access_token=user.azure_credentials["access_token"],
                tenant_id=user.azure_credentials.get("tenant_id", user.tenant_id or ""),
            ))

        # Inject GCP credentials if available
        if user.gcp_credentials:
            cred_env.update(self.credential_injector.inject_gcp_token(
                access_token=user.gcp_credentials["access_token"],
                project_id=user.gcp_credentials.get("project_id"),
            ))

        # Create executor with user's credentials
        cred_provider = CredentialProvider()
        config = SandboxConfig(
            timeout_seconds=60,
            env_allowlist=list(cred_env.keys()),
        )

        # Inject credentials into environment
        for key, value in cred_env.items():
            os.environ[key] = value

        try:
            executor = Executor(
                config=config,
                credential_provider=cred_provider,
            )
            return await executor.execute(tool)
        finally:
            # Clean up injected credentials
            for key in cred_env:
                os.environ.pop(key, None)
            self.credential_injector.cleanup()


# Example usage in AgenticWork platform:
"""
# In your platform's API handler:

async def handle_oat_request(request: Request):
    # Get authenticated user from SSO
    user = PlatformUser(
        user_id=request.user.id,
        email=request.user.email,
        display_name=request.user.name,
        provider="azure",  # or "google"
        tenant_id=request.user.tenant_id,

        # User's linked cloud credentials (from platform's credential store)
        aws_credentials=get_user_aws_creds(request.user.id),
        azure_credentials=get_user_azure_creds(request.user.id),
        gcp_credentials=get_user_gcp_creds(request.user.id),
    )

    # Create Synth client
    client = PlatformSynthClient(
        llm_provider="bedrock",
        llm_model="us.anthropic.claude-opus-4-6-v1",
        log_file=Path("/var/log/oat/usage.jsonl"),
        on_usage_report=lambda m: billing_service.record_usage(
            user_id=m.user_id,
            cost_usd=m.cost_usd,
            tokens=m.tokens.total_tokens,
        ),
    )

    # Execute as user
    result = await client.synthesize_and_execute(
        intent=request.body.intent,
        user=user,
        auto_approve_low_risk=True,
        approval_callback=lambda req: get_user_approval_via_websocket(req),
    )

    return {
        "success": result.success,
        "result": result.result,
        "metrics": {
            "cost_usd": result.metrics.cost_usd,
            "total_time_ms": result.metrics.total_time_ms,
        },
    }
"""
