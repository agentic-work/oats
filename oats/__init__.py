"""
OATS — On-demand Agent Tool Synthesis

LLMs synthesize custom tools on-the-fly with mandatory human approval.
https://oats.agenticwork.io | https://github.com/agentic-work/oats
"""

__version__ = "0.6.0"

from oats.core.executor import Executor
from oats.core.registry import CapabilityRegistry
from oats.core.synthesizer import Synthesizer
from oats.core.types import (
    ApprovalDecision,
    ApprovalRequest,
    AuthType,
    Capability,
    CapabilityAuth,
    RiskLevel,
    SynthesizedTool,
    ToolOutput,
)
from oats.hitl.gate import HITLGate

__all__ = [
    # Types
    "AuthType",
    "Capability",
    "CapabilityAuth",
    "SynthesizedTool",
    "ToolOutput",
    "RiskLevel",
    "ApprovalRequest",
    "ApprovalDecision",
    # Core
    "CapabilityRegistry",
    "Synthesizer",
    "Executor",
    "HITLGate",
]
