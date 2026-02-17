"""
OATS Platform Integration

Integrates OATS with the AgenticWork platform for:
- SSO credential injection
- Usage metering and audit trails
- Capability governance
"""

from oats.platform.integration import PlatformSynthClient

__all__ = ["PlatformSynthClient"]
