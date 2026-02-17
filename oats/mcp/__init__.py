"""OATS MCP Server — Expose OATS as an MCP tool for Claude Code"""

from oats.mcp.server import MCPServer
from oats.mcp.server import main as serve

__all__ = ["MCPServer", "serve"]
