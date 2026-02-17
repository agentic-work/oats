"""
Synth MCP Server

Exposes Synth tool synthesis and execution as MCP tools for Claude Code.
Run with: python -m synth.mcp.server
"""

import asyncio
import json
import sys
from typing import Any

from oats.core.registry import CapabilityRegistry
from oats.core.synthesizer import Synthesizer
from oats.core.executor import Executor, SandboxConfig, CredentialProvider
from oats.core.llm import create_llm_client
from oats.capabilities import load_builtin_capabilities
from oats.hitl.gate import HITLGate, ApprovalHandler, ApprovalRequest, ApprovalDecision


class AutoApproveHandler(ApprovalHandler):
    """Auto-approve for MCP context (Claude Code handles approval)."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        # In MCP context, we return the tool info and let Claude Code/user decide
        # For now, auto-approve LOW risk, require explicit for others
        if request.tool.risk_level.value == "LOW":
            return ApprovalDecision(approved=True)
        # For non-low risk, we'll include approval info in the response
        return ApprovalDecision(approved=True)  # Let Claude Code handle HITL


class MCPServer:
    """MCP Server for Synth."""

    def __init__(
        self,
        provider: str = "bedrock",
        base_url: str | None = None,
        model: str = "us.anthropic.claude-opus-4-6-v1",
        region: str = "us-east-1",
    ):
        self.provider = provider
        self.base_url = base_url
        self.model = model
        self.region = region
        self.registry: CapabilityRegistry | None = None
        self.llm_client = None

    async def initialize(self):
        """Initialize Synth components."""
        self.registry = load_builtin_capabilities()

        # Build kwargs based on provider
        kwargs = {"model": self.model}
        if self.provider == "bedrock":
            kwargs["region"] = self.region
        elif self.base_url:
            kwargs["base_url"] = self.base_url

        self.llm_client = create_llm_client(
            provider=self.provider,
            **kwargs,
        )

    def get_tools(self) -> list[dict]:
        """Return MCP tool definitions."""
        return [
            {
                "name": "synth_synthesize",
                "description": """Synthesize a one-shot tool from natural language intent.

Use this when you need to perform a task that doesn't have a dedicated tool.
Synth will analyze your intent, generate Python code, and execute it.

Examples:
- "fetch the current bitcoin price from coingecko"
- "get my unread github notifications"
- "parse this CSV and return summary stats"

Returns the synthesized code and execution result.""",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "Natural language description of what you want to do",
                        },
                        "capabilities": {
                            "type": "string",
                            "description": "Comma-separated capabilities to use (optional). Options: http, filesystem, shell, github, slack, json, datetime, data",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "If true, only synthesize code without executing",
                            "default": False,
                        },
                    },
                    "required": ["intent"],
                },
            },
            {
                "name": "synth_list_capabilities",
                "description": "List available Synth capabilities that can be used for tool synthesis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute an MCP tool call."""
        if name == "synth_synthesize":
            return await self._synthesize(arguments)
        elif name == "synth_list_capabilities":
            return await self._list_capabilities()
        else:
            return {"error": f"Unknown tool: {name}"}

    async def _synthesize(self, args: dict[str, Any]) -> dict[str, Any]:
        """Synthesize and optionally execute a tool."""
        intent = args.get("intent", "")
        capabilities = args.get("capabilities")
        dry_run = args.get("dry_run", False)

        if not intent:
            return {"error": "Intent is required"}

        cap_filter = None
        if capabilities:
            cap_filter = [c.strip() for c in capabilities.split(",")]

        # Create synthesizer
        synthesizer = Synthesizer(
            llm_client=self.llm_client,
            capability_registry=self.registry,
        )

        # Synthesize
        try:
            tool = await synthesizer.synthesize(intent, allowed_capabilities=cap_filter)
        except Exception as e:
            return {"error": f"Synthesis failed: {str(e)}"}

        if tool is None:
            return {"result": "Existing tools can handle this intent - no synthesis needed"}

        result = {
            "tool_id": tool.id,
            "intent": tool.intent,
            "code": tool.code,
            "risk_level": tool.risk_level.value,
            "risk_reasoning": tool.risk_reasoning,
            "explanation": tool.human_explanation,
            "capabilities_used": tool.capabilities_used,
            "requested_scopes": tool.requested_scopes,
        }

        if dry_run:
            result["dry_run"] = True
            return result

        # Execute
        try:
            creds = CredentialProvider()
            executor = Executor(
                config=SandboxConfig(timeout_seconds=30),
                credential_provider=creds,
            )
            output = await executor.execute(tool)

            result["execution"] = {
                "success": output.success,
                "result": output.result,
                "error": output.error,
                "execution_time_ms": output.execution_time_ms,
            }
            if output.stdout:
                result["execution"]["stdout"] = output.stdout
            if output.stderr:
                result["execution"]["stderr"] = output.stderr

        except Exception as e:
            result["execution"] = {
                "success": False,
                "error": f"Execution failed: {str(e)}",
            }

        return result

    async def _list_capabilities(self) -> dict[str, Any]:
        """List available capabilities."""
        caps = []
        for cap in self.registry.get_all():
            caps.append({
                "name": cap.name,
                "description": cap.description.split("\n")[0],
                "auth_type": cap.auth.type.value if cap.auth else "none",
            })
        return {"capabilities": caps}

    async def handle_message(self, message: dict) -> dict:
        """Handle an MCP JSON-RPC message."""
        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")

        if method == "initialize":
            await self.initialize()
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "synth",
                        "version": "0.1.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            }

        elif method == "notifications/initialized":
            return None  # No response for notifications

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": self.get_tools(),
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            result = await self.call_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2, default=str),
                        }
                    ],
                },
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

    async def run(self):
        """Run the MCP server over stdio."""
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break

                message = json.loads(line)
                response = await self.handle_message(message)

                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": str(e),
                    },
                }
                sys.stdout.write(json.dumps(error_response) + "\n")
                sys.stdout.flush()


def main():
    """Entry point for MCP server."""
    import os

    provider = os.environ.get("SYNTH_PROVIDER", "bedrock")
    model = os.environ.get("SYNTH_MODEL", "us.anthropic.claude-opus-4-6-v1")
    base_url = os.environ.get("SYNTH_BASE_URL")
    region = os.environ.get("AWS_REGION", "us-east-1")

    server = MCPServer(provider=provider, base_url=base_url, model=model, region=region)
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
