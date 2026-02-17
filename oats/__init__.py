"""
Synth - Tool Synthesis Framework

Enables LLMs to synthesize and execute one-shot tools with human-in-the-loop approval.
"""

__version__ = "0.1.0"

from oats.core.types import (
    Capability,
    CapabilityAuth,
    SynthesizedTool,
    ToolOutput,
    RiskLevel,
    ApprovalRequest,
    ApprovalDecision,
)
from oats.core.registry import CapabilityRegistry
from oats.core.synthesizer import Synthesizer
from oats.core.executor import Executor
from oats.hitl.gate import HITLGate

__all__ = [
    # Types
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
