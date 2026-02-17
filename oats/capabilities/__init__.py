"""Synth Capabilities - Built-in capability definitions"""

from pathlib import Path
from oats.core.registry import CapabilityRegistry


def load_builtin_capabilities() -> CapabilityRegistry:
    """
    Load the built-in capability definitions.

    Returns a CapabilityRegistry pre-populated with standard capabilities
    like http, filesystem, github, slack, etc.
    """
    registry = CapabilityRegistry()
    builtin_path = Path(__file__).parent / "builtin.yaml"

    if builtin_path.exists():
        registry.load_from_yaml(builtin_path)

    return registry


def get_builtin_path() -> Path:
    """Get the path to the built-in capabilities YAML file."""
    return Path(__file__).parent / "builtin.yaml"


__all__ = ["load_builtin_capabilities", "get_builtin_path"]
