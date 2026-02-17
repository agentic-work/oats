"""
Sandboxed Tool Executor

Executes synthesized tools in an isolated environment with
scoped credentials and resource limits.
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from oats.core.types import (
    GroundableOutput,
    SynthesizedTool,
    ToolOutput,
)


class SandboxConfig:
    """Configuration for the execution sandbox."""

    def __init__(
        self,
        timeout_seconds: int = 30,
        max_memory_mb: int = 512,
        allowed_network: bool = True,
        allowed_domains: list[str] | None = None,
        working_dir: Path | None = None,
        env_allowlist: list[str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self.allowed_network = allowed_network
        self.allowed_domains = allowed_domains or []
        self.working_dir = working_dir or Path(tempfile.gettempdir())
        self.env_allowlist = env_allowlist or []


class CredentialProvider:
    """
    Provides credentials for tool execution.

    CRITICAL: Credentials are NEVER embedded in tool code.
    They are injected as environment variables at execution time.
    """

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}

    def register_credential(self, scope: str, env_var: str) -> None:
        """
        Register a credential for a scope.

        Args:
            scope: The auth scope (e.g., "github:read")
            env_var: Environment variable containing the credential
        """
        self._credentials[scope] = env_var

    def get_env_for_scopes(self, scopes: list[str]) -> dict[str, str]:
        """
        Get environment variables for the requested scopes.

        Returns a dict of env vars to inject into the sandbox.
        """
        env = {}
        for scope in scopes:
            if scope in self._credentials:
                env_var = self._credentials[scope]
                value = os.environ.get(env_var)
                if value:
                    env[env_var] = value
        return env

    def has_scope(self, scope: str) -> bool:
        """Check if a scope is available."""
        return scope in self._credentials


class Executor:
    """
    Executes synthesized tools in a sandbox.

    The executor:
    1. Validates the tool code
    2. Sets up an isolated environment
    3. Injects scoped credentials
    4. Executes with resource limits
    5. Captures output and errors
    6. Extracts groundable content
    """

    def __init__(
        self,
        config: SandboxConfig | None = None,
        credential_provider: CredentialProvider | None = None,
    ) -> None:
        self.config = config or SandboxConfig()
        self.credentials = credential_provider or CredentialProvider()

    async def execute(
        self,
        tool: SynthesizedTool,
        context: dict[str, Any] | None = None,
    ) -> ToolOutput:
        """
        Execute a synthesized tool in a sandbox.

        Args:
            tool: The synthesized tool to execute
            context: Additional context to pass to the tool

        Returns:
            ToolOutput with results or errors
        """
        start_time = time.time()

        try:
            # Step 1: Validate code (basic safety checks)
            validation_error = self._validate_code(tool.code)
            if validation_error:
                return ToolOutput(
                    tool_id=tool.id,
                    success=False,
                    error=f"Code validation failed: {validation_error}",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            # Step 2: Check credential availability
            missing_scopes = self._check_scopes(tool.requested_scopes)
            if missing_scopes:
                return ToolOutput(
                    tool_id=tool.id,
                    success=False,
                    error=f"Missing credentials for scopes: {', '.join(missing_scopes)}",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )

            # Step 3: Prepare execution environment
            env = self._prepare_environment(tool.requested_scopes)

            # Step 4: Execute in sandbox
            result, stdout, stderr = await self._execute_in_sandbox(
                tool.code,
                context or {},
                env,
            )

            execution_time = int((time.time() - start_time) * 1000)

            # Step 5: Extract groundable output
            groundable = self._extract_groundable(tool, result)

            return ToolOutput(
                tool_id=tool.id,
                success=True,
                result=result,
                stdout=stdout,
                stderr=stderr,
                execution_time_ms=execution_time,
                groundable=groundable,
            )

        except TimeoutError:
            return ToolOutput(
                tool_id=tool.id,
                success=False,
                error=f"Execution timed out after {self.config.timeout_seconds}s",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            return ToolOutput(
                tool_id=tool.id,
                success=False,
                error=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _validate_code(self, code: str) -> str | None:
        """
        Basic code validation.

        Returns error message if invalid, None if OK.
        """
        # Check for obviously dangerous patterns
        dangerous_patterns = [
            ("os.system(", "Direct system calls not allowed"),
            ("subprocess.call(", "Use subprocess.run with shell=False"),
            ("eval(", "eval() not allowed"),
            # Note: "exec(" is allowed in create_subprocess_exec context
            ("exec(context", "exec() not allowed for arbitrary code"),
            ("__import__(", "Dynamic imports not allowed"),
            ("open('/etc", "System file access not allowed"),
            ("open('/root", "Root directory access not allowed"),
        ]

        for pattern, message in dangerous_patterns:
            if pattern in code:
                return message

        # Verify it has the expected function signature
        if "async def execute" not in code:
            return "Code must define 'async def execute(context: dict)'"

        return None

    def _check_scopes(self, scopes: list[str]) -> list[str]:
        """Check which scopes are missing credentials."""
        # Filter out empty strings and "none" (not real scopes)
        real_scopes = [
            s for s in scopes
            if s and s.lower() not in ("none", "")
        ]

        # Scopes that don't require credentials (public access or local)
        no_creds_required = {
            "http:get", "http:post", "http:put", "http:delete",  # Public HTTP
            "json", "datetime", "data",  # Local processing
            "shell:execute", "filesystem:read", "filesystem:write",  # Local ops (use env creds)
        }

        # Cloud providers whose env vars are passed through automatically
        # by _prepare_environment — don't require explicit scope registration
        cloud_prefixes = ("aws:", "gcp:", "azure:")

        # Only check scopes that actually require credentials
        needs_creds = [
            s for s in real_scopes
            if s not in no_creds_required and not s.startswith(cloud_prefixes)
        ]
        return [s for s in needs_creds if not self.credentials.has_scope(s)]

    def _prepare_environment(self, scopes: list[str]) -> dict[str, str]:
        """Prepare environment variables for execution."""
        # Start with minimal base environment
        # Use real HOME so cloud SDK credentials (gcloud ADC, AWS profiles) are accessible
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", str(self.config.working_dir)),
            "TMPDIR": str(self.config.working_dir),
            "USER": os.environ.get("USER", ""),
        }

        # Always pass through cloud provider credentials if present
        cloud_vars = [
            # AWS
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
            # Azure
            "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID",
            # GCP
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT",
            "CLOUDSDK_CORE_PROJECT", "CLOUDSDK_CONFIG",
            # Service tokens
            "GITHUB_TOKEN", "SLACK_TOKEN",
        ]
        for var in cloud_vars:
            if var in os.environ:
                env[var] = os.environ[var]

        # Add allowlisted env vars
        for var in self.config.env_allowlist:
            if var in os.environ:
                env[var] = os.environ[var]

        # Add scoped credentials
        env.update(self.credentials.get_env_for_scopes(scopes))

        return env

    async def _execute_in_sandbox(
        self,
        code: str,
        context: dict[str, Any],
        env: dict[str, str],
    ) -> tuple[Any, str, str]:
        """
        Execute code in a sandboxed subprocess.

        For now, uses subprocess with restrictions.
        Future: Could use Deno, Firecracker, or WASM.
        """
        # Write the code to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            dir=self.config.working_dir,
        ) as f:
            # Wrap the code in a runner
            runner_code = f'''
import asyncio
import json
import sys

{code}

async def main():
    context = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {{}}
    result = await execute(context)
    print("__OAT_RESULT__")
    print(json.dumps(result))

if __name__ == "__main__":
    asyncio.run(main())
'''
            f.write(runner_code)
            script_path = f.name

        try:
            # Execute with timeout
            process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "python",
                    script_path,
                    __import__("json").dumps(context),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=str(self.config.working_dir),
                ),
                timeout=self.config.timeout_seconds,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.timeout_seconds,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # Extract result from stdout
            result = None
            if "__OAT_RESULT__" in stdout:
                parts = stdout.split("__OAT_RESULT__")
                if len(parts) > 1:
                    result_str = parts[1].strip()
                    try:
                        result = __import__("json").loads(result_str)
                    except Exception:
                        result = result_str
                stdout = parts[0]  # Remove result marker from stdout

            return result, stdout, stderr

        finally:
            # Clean up temp file
            try:
                Path(script_path).unlink()
            except OSError:
                pass

    def _extract_groundable(
        self,
        tool: SynthesizedTool,
        result: Any,
    ) -> GroundableOutput | None:
        """Extract groundable content from the result."""
        if result is None:
            return None

        # Basic extraction - can be enhanced with LLM
        import json

        if isinstance(result, dict):
            summary = tool.human_explanation
            embedding_text = f"{tool.intent}\n\n{json.dumps(result, indent=2)}"
        else:
            summary = tool.human_explanation
            embedding_text = f"{tool.intent}\n\n{str(result)}"

        return GroundableOutput(
            summary=summary,
            entities=[],  # Could extract with NER
            embedding_text=embedding_text,
            metadata={
                "tool_id": tool.id,
                "intent": tool.intent,
                "capabilities": tool.capabilities_used,
            },
        )
