"""
Synth Metrics and Logging

Comprehensive observability for every Synth synthesis and execution:
- TTFT (time to first token)
- Input/output token counts
- Provider and model
- Cost calculation
- Failures and retries
- User identity
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from oats.core.types import RiskLevel

# Model pricing per 1M tokens (as of 2024)
MODEL_PRICING = {
    # Anthropic Direct API
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-20250514": {"input": 0.25, "output": 1.25},

    # Bedrock (slightly different pricing)
    "us.anthropic.claude-opus-4-6-v1": {"input": 15.0, "output": 75.0},
    "us.anthropic.claude-opus-4-5-20251101-v1:0": {"input": 15.0, "output": 75.0},
    "us.anthropic.claude-sonnet-4-20250514-v1:0": {"input": 3.0, "output": 15.0},
    "anthropic.claude-sonnet-4-20250514-v1:0": {"input": 3.0, "output": 15.0},

    # Ollama (free, local)
    "gpt-oss": {"input": 0.0, "output": 0.0},
    "llama3.2": {"input": 0.0, "output": 0.0},
    "qwen2.5:32b": {"input": 0.0, "output": 0.0},

    # Default fallback
    "default": {"input": 3.0, "output": 15.0},
}


class EventType(StrEnum):
    SYNTHESIS_START = "synthesis_start"
    SYNTHESIS_COMPLETE = "synthesis_complete"
    SYNTHESIS_FAILED = "synthesis_failed"
    EXECUTION_START = "execution_start"
    EXECUTION_COMPLETE = "execution_complete"
    EXECUTION_FAILED = "execution_failed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    RETRY = "retry"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def calculate_cost(self, model: str) -> float:
        """Calculate cost in USD."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
        input_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost


@dataclass
class SynthesisMetrics:
    """Metrics for a single synthesis operation."""
    # Identifiers
    tool_id: str
    intent: str
    session_id: str | None = None

    # Provider info
    provider: str = ""
    model: str = ""

    # User identity
    user_id: str | None = None
    user_email: str | None = None
    user_provider: str | None = None  # aws, azure, gcp

    # Timing
    start_time: float = 0.0
    ttft_ms: float | None = None  # Time to first token
    synthesis_time_ms: float = 0.0
    execution_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # Tokens and cost
    tokens: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0

    # Status
    synthesis_success: bool = False
    execution_success: bool = False
    risk_level: str = ""
    capabilities_used: list[str] = field(default_factory=list)

    # Errors and retries
    error: str | None = None
    retry_count: int = 0
    failure_reason: str | None = None

    # Timestamps
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON logging."""
        return asdict(self)

    def to_log_line(self) -> str:
        """Format as structured log line."""
        return json.dumps(self.to_dict(), default=str)


class MetricsCollector:
    """Collects and emits metrics for Synth operations."""

    def __init__(
        self,
        log_file: Path | None = None,
        emit_to_stdout: bool = False,
    ):
        self.log_file = log_file
        self.emit_to_stdout = emit_to_stdout
        self._logger = logging.getLogger("oat.metrics")

        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def start_synthesis(
        self,
        tool_id: str,
        intent: str,
        provider: str,
        model: str,
        user_identity: dict | None = None,
        session_id: str | None = None,
    ) -> SynthesisMetrics:
        """Start tracking a synthesis operation."""
        metrics = SynthesisMetrics(
            tool_id=tool_id,
            intent=intent,
            provider=provider,
            model=model,
            session_id=session_id,
            start_time=time.time(),
        )

        if user_identity:
            metrics.user_id = user_identity.get("user_id")
            metrics.user_email = user_identity.get("email")
            metrics.user_provider = user_identity.get("provider")

        self._emit_event(EventType.SYNTHESIS_START, metrics)
        return metrics

    def record_ttft(self, metrics: SynthesisMetrics) -> None:
        """Record time to first token."""
        metrics.ttft_ms = (time.time() - metrics.start_time) * 1000

    def record_synthesis_complete(
        self,
        metrics: SynthesisMetrics,
        tokens: TokenUsage,
        risk_level: RiskLevel,
        capabilities: list[str],
    ) -> None:
        """Record successful synthesis."""
        metrics.synthesis_time_ms = (time.time() - metrics.start_time) * 1000
        metrics.tokens = tokens
        metrics.cost_usd = tokens.calculate_cost(metrics.model)
        metrics.risk_level = risk_level.value
        metrics.capabilities_used = capabilities
        metrics.synthesis_success = True

        self._emit_event(EventType.SYNTHESIS_COMPLETE, metrics)

    def record_synthesis_failed(
        self,
        metrics: SynthesisMetrics,
        error: str,
        retry_count: int = 0,
    ) -> None:
        """Record synthesis failure."""
        metrics.synthesis_time_ms = (time.time() - metrics.start_time) * 1000
        metrics.synthesis_success = False
        metrics.error = error
        metrics.retry_count = retry_count

        self._emit_event(EventType.SYNTHESIS_FAILED, metrics)

    def record_execution_complete(
        self,
        metrics: SynthesisMetrics,
        success: bool,
        execution_time_ms: float,
        error: str | None = None,
    ) -> None:
        """Record execution result."""
        metrics.execution_time_ms = execution_time_ms
        metrics.execution_success = success
        metrics.total_time_ms = (time.time() - metrics.start_time) * 1000

        if error:
            metrics.error = error

        event = EventType.EXECUTION_COMPLETE if success else EventType.EXECUTION_FAILED
        self._emit_event(event, metrics)

    def record_approval(
        self,
        metrics: SynthesisMetrics,
        approved: bool,
        reason: str | None = None,
    ) -> None:
        """Record approval decision."""
        if not approved:
            metrics.failure_reason = reason or "User denied"

        event = EventType.APPROVAL_GRANTED if approved else EventType.APPROVAL_DENIED
        self._emit_event(event, metrics)

    def record_retry(self, metrics: SynthesisMetrics, reason: str) -> None:
        """Record a retry attempt."""
        metrics.retry_count += 1
        self._emit_event(EventType.RETRY, metrics, extra={"retry_reason": reason})

    def _emit_event(
        self,
        event_type: EventType,
        metrics: SynthesisMetrics,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit a metrics event."""
        event = {
            "event": event_type.value,
            "timestamp": datetime.now(UTC).isoformat(),
            **metrics.to_dict(),
        }
        if extra:
            event.update(extra)

        log_line = json.dumps(event, default=str)

        if self.emit_to_stdout:
            print(f"[Synth] {log_line}")

        self._logger.info(log_line)

    def get_summary(self, metrics: SynthesisMetrics) -> str:
        """Get human-readable summary."""
        return f"""
╭─────────────────── Synth Metrics ───────────────────╮
│ Tool ID: {metrics.tool_id[:36]}
│ Provider: {metrics.provider} / {metrics.model}
│ User: {metrics.user_email or metrics.user_id or 'unknown'}
├───────────────────────────────────────────────────┤
│ TTFT: {metrics.ttft_ms:.0f}ms
│ Synthesis: {metrics.synthesis_time_ms:.0f}ms
│ Execution: {metrics.execution_time_ms:.0f}ms
│ Total: {metrics.total_time_ms:.0f}ms
├───────────────────────────────────────────────────┤
│ Input tokens: {metrics.tokens.input_tokens:,}
│ Output tokens: {metrics.tokens.output_tokens:,}
│ Cost: ${metrics.cost_usd:.6f}
├───────────────────────────────────────────────────┤
│ Risk: {metrics.risk_level}
│ Success: {'✓' if metrics.execution_success else '✗'}
│ Retries: {metrics.retry_count}
╰───────────────────────────────────────────────────╯
"""


# Global metrics collector (can be configured)
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def configure_metrics(
    log_file: Path | None = None,
    emit_to_stdout: bool = False,
) -> None:
    """Configure the global metrics collector."""
    global _metrics_collector
    _metrics_collector = MetricsCollector(
        log_file=log_file,
        emit_to_stdout=emit_to_stdout,
    )
