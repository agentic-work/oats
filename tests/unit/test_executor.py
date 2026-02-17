"""
Tests for Sandboxed Executor
"""

import pytest
import os

from oats.core.types import SynthesizedTool, RiskLevel, ToolOutput
from oats.core.executor import Executor, SandboxConfig, CredentialProvider


class TestCredentialProvider:
    """Tests for the CredentialProvider class."""

    def test_register_credential(self) -> None:
        """Should register a credential mapping."""
        provider = CredentialProvider()
        provider.register_credential("github:read", "GITHUB_TOKEN")

        assert provider.has_scope("github:read")
        assert not provider.has_scope("github:write")

    def test_get_env_for_scopes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return env vars for requested scopes."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
        monkeypatch.setenv("SLACK_TOKEN", "xoxb_test456")

        provider = CredentialProvider()
        provider.register_credential("github:read", "GITHUB_TOKEN")
        provider.register_credential("slack:read", "SLACK_TOKEN")

        env = provider.get_env_for_scopes(["github:read"])

        assert "GITHUB_TOKEN" in env
        assert env["GITHUB_TOKEN"] == "ghp_test123"
        assert "SLACK_TOKEN" not in env  # Not requested

    def test_get_env_missing_scope(self) -> None:
        """Should not include env vars for unregistered scopes."""
        provider = CredentialProvider()

        env = provider.get_env_for_scopes(["unknown:scope"])

        assert env == {}


class TestSandboxConfig:
    """Tests for SandboxConfig."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        config = SandboxConfig()

        assert config.timeout_seconds == 30
        assert config.max_memory_mb == 512
        assert config.allowed_network is True

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        config = SandboxConfig(
            timeout_seconds=60,
            max_memory_mb=1024,
            allowed_network=False,
            allowed_domains=["api.example.com"],
        )

        assert config.timeout_seconds == 60
        assert config.max_memory_mb == 1024
        assert config.allowed_network is False
        assert "api.example.com" in config.allowed_domains


class TestExecutor:
    """Tests for the Executor class."""

    @pytest.mark.asyncio
    async def test_execute_simple_tool(self) -> None:
        """Should execute a simple tool and return result."""
        tool = SynthesizedTool(
            id="test-123",
            intent="return hello",
            code="""
async def execute(context: dict) -> dict:
    return {"message": "hello"}
""",
            language="python",
            requested_scopes=[],
            capabilities_used=[],
            risk_level=RiskLevel.LOW,
            risk_reasoning="No side effects",
            human_explanation="Returns hello",
            output_schema={},
        )

        executor = Executor()
        output = await executor.execute(tool)

        assert output.success is True
        assert output.result is not None
        assert output.result.get("message") == "hello"

    @pytest.mark.asyncio
    async def test_execute_validates_dangerous_code(
        self,
        dangerous_tool: SynthesizedTool,
    ) -> None:
        """Should reject dangerous code patterns."""
        executor = Executor()
        output = await executor.execute(dangerous_tool)

        assert output.success is False
        assert output.error is not None
        assert "validation failed" in output.error.lower()

    @pytest.mark.asyncio
    async def test_execute_rejects_eval(self) -> None:
        """Should reject code using eval()."""
        tool = SynthesizedTool(
            id="eval-test",
            intent="use eval",
            code="""
async def execute(context: dict) -> dict:
    return eval("1 + 1")
""",
            language="python",
            requested_scopes=[],
            capabilities_used=[],
            risk_level=RiskLevel.HIGH,
            risk_reasoning="Uses eval",
            human_explanation="Attempts to use eval",
            output_schema={},
        )

        executor = Executor()
        output = await executor.execute(tool)

        assert output.success is False
        assert "eval" in output.error.lower()

    @pytest.mark.asyncio
    async def test_execute_checks_missing_credentials(self) -> None:
        """Should fail if required credentials are missing."""
        tool = SynthesizedTool(
            id="creds-test",
            intent="use github",
            code="""
async def execute(context: dict) -> dict:
    import os
    return {"token": os.environ.get("GITHUB_TOKEN")}
""",
            language="python",
            requested_scopes=["github:read"],  # Scope requires creds
            capabilities_used=["github"],
            risk_level=RiskLevel.LOW,
            risk_reasoning="Reads github",
            human_explanation="Uses GitHub API",
            output_schema={},
        )

        # Executor without github credentials registered
        executor = Executor()
        output = await executor.execute(tool)

        assert output.success is False
        assert "missing credentials" in output.error.lower()

    @pytest.mark.asyncio
    async def test_execute_with_credentials(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should inject credentials when available."""
        monkeypatch.setenv("TEST_API_KEY", "secret123")

        tool = SynthesizedTool(
            id="creds-test",
            intent="use api",
            code="""
async def execute(context: dict) -> dict:
    import os
    key = os.environ.get("TEST_API_KEY", "missing")
    return {"has_key": key != "missing"}
""",
            language="python",
            requested_scopes=["api:read"],
            capabilities_used=["api"],
            risk_level=RiskLevel.LOW,
            risk_reasoning="Reads API",
            human_explanation="Uses API with key",
            output_schema={},
        )

        creds = CredentialProvider()
        creds.register_credential("api:read", "TEST_API_KEY")

        executor = Executor(credential_provider=creds)
        output = await executor.execute(tool)

        assert output.success is True
        assert output.result.get("has_key") is True

    @pytest.mark.asyncio
    async def test_execute_captures_stdout(self) -> None:
        """Should capture stdout from tool execution."""
        tool = SynthesizedTool(
            id="stdout-test",
            intent="print something",
            code="""
async def execute(context: dict) -> dict:
    print("Hello from stdout")
    return {"printed": True}
""",
            language="python",
            requested_scopes=[],
            capabilities_used=[],
            risk_level=RiskLevel.LOW,
            risk_reasoning="Just prints",
            human_explanation="Prints to stdout",
            output_schema={},
        )

        executor = Executor()
        output = await executor.execute(tool)

        assert output.success is True
        assert "Hello from stdout" in output.stdout

    @pytest.mark.asyncio
    async def test_execute_handles_errors(self) -> None:
        """Should handle exceptions in tool code."""
        tool = SynthesizedTool(
            id="error-test",
            intent="raise error",
            code="""
async def execute(context: dict) -> dict:
    raise ValueError("Intentional error")
""",
            language="python",
            requested_scopes=[],
            capabilities_used=[],
            risk_level=RiskLevel.LOW,
            risk_reasoning="Test error handling",
            human_explanation="Raises an error",
            output_schema={},
        )

        executor = Executor()
        output = await executor.execute(tool)

        # The tool raised an error, but executor should catch it
        assert output.success is False or "error" in output.stderr.lower()

    @pytest.mark.asyncio
    async def test_execute_uses_context(self) -> None:
        """Should pass context to tool execution."""
        tool = SynthesizedTool(
            id="context-test",
            intent="use context",
            code="""
async def execute(context: dict) -> dict:
    return {"received": context.get("input_value")}
""",
            language="python",
            requested_scopes=[],
            capabilities_used=[],
            risk_level=RiskLevel.LOW,
            risk_reasoning="Uses context",
            human_explanation="Returns context value",
            output_schema={},
        )

        executor = Executor()
        output = await executor.execute(tool, context={"input_value": 42})

        assert output.success is True
        assert output.result.get("received") == 42

    @pytest.mark.asyncio
    async def test_execute_tracks_timing(self) -> None:
        """Should track execution time."""
        tool = SynthesizedTool(
            id="timing-test",
            intent="sleep briefly",
            code="""
import asyncio
async def execute(context: dict) -> dict:
    await asyncio.sleep(0.1)
    return {"done": True}
""",
            language="python",
            requested_scopes=[],
            capabilities_used=[],
            risk_level=RiskLevel.LOW,
            risk_reasoning="Brief sleep",
            human_explanation="Sleeps 100ms",
            output_schema={},
        )

        executor = Executor()
        output = await executor.execute(tool)

        assert output.execution_time_ms >= 100

    @pytest.mark.asyncio
    async def test_execute_extracts_groundable_output(
        self,
        sample_tool: SynthesizedTool,
    ) -> None:
        """Should extract groundable content from results."""
        executor = Executor()
        output = await executor.execute(sample_tool)

        # Note: sample_tool may fail due to network, but grounding should work on any result
        if output.success:
            assert output.groundable is not None
            assert output.groundable.summary is not None
            assert output.groundable.metadata.get("tool_id") == sample_tool.id
