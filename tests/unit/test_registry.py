"""
Tests for CapabilityRegistry
"""

import pytest
import tempfile
from pathlib import Path

from oats.core.types import Capability, CapabilityAuth, AuthType
from oats.core.registry import CapabilityRegistry, create_http_capability


class TestCapabilityRegistry:
    """Tests for the CapabilityRegistry class."""

    def test_register_capability(self, http_capability: Capability) -> None:
        """Should register a capability."""
        registry = CapabilityRegistry()
        registry.register(http_capability)

        assert registry.has("http")
        assert len(registry) == 1

    def test_get_capability(self, http_capability: Capability) -> None:
        """Should retrieve a registered capability."""
        registry = CapabilityRegistry()
        registry.register(http_capability)

        cap = registry.get("http")
        assert cap is not None
        assert cap.name == "http"
        assert cap.description == "Make HTTP requests"

    def test_get_nonexistent_capability(self) -> None:
        """Should return None for unregistered capability."""
        registry = CapabilityRegistry()
        assert registry.get("nonexistent") is None

    def test_register_many(
        self,
        http_capability: Capability,
        github_capability: Capability,
    ) -> None:
        """Should register multiple capabilities at once."""
        registry = CapabilityRegistry()
        registry.register_many([http_capability, github_capability])

        assert len(registry) == 2
        assert registry.has("http")
        assert registry.has("github")

    def test_get_all(self, capability_registry: CapabilityRegistry) -> None:
        """Should return all registered capabilities."""
        caps = capability_registry.get_all()
        assert len(caps) == 3
        names = [c.name for c in caps]
        assert "http" in names
        assert "github" in names
        assert "filesystem" in names

    def test_get_names(self, capability_registry: CapabilityRegistry) -> None:
        """Should return all capability names."""
        names = capability_registry.get_names()
        assert len(names) == 3
        assert "http" in names

    def test_remove_capability(self, capability_registry: CapabilityRegistry) -> None:
        """Should remove a capability."""
        assert capability_registry.has("http")
        result = capability_registry.remove("http")
        assert result is True
        assert not capability_registry.has("http")

    def test_remove_nonexistent(self, capability_registry: CapabilityRegistry) -> None:
        """Should return False when removing nonexistent capability."""
        result = capability_registry.remove("nonexistent")
        assert result is False

    def test_clear(self, capability_registry: CapabilityRegistry) -> None:
        """Should clear all capabilities."""
        assert len(capability_registry) > 0
        capability_registry.clear()
        assert len(capability_registry) == 0

    def test_iteration(self, capability_registry: CapabilityRegistry) -> None:
        """Should support iteration."""
        names = [cap.name for cap in capability_registry]
        assert len(names) == 3

    def test_contains(self, capability_registry: CapabilityRegistry) -> None:
        """Should support 'in' operator."""
        assert "http" in capability_registry
        assert "nonexistent" not in capability_registry

    def test_get_scopes_for_capability(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should return auth scopes for a capability."""
        scopes = capability_registry.get_scopes_for_capability("github")
        assert "repo:read" in scopes
        assert "repo:write" in scopes
        assert "user:read" in scopes

    def test_get_scopes_for_no_auth_capability(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should return empty list for capability with no auth scopes."""
        scopes = capability_registry.get_scopes_for_capability("http")
        assert scopes == []

    def test_filter_by_auth_type(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should filter capabilities by auth type."""
        bearer_caps = capability_registry.filter_by_auth_type(AuthType.BEARER)
        assert len(bearer_caps) == 1
        assert bearer_caps[0].name == "github"

    def test_to_synthesis_context(
        self,
        capability_registry: CapabilityRegistry,
    ) -> None:
        """Should generate synthesis context string."""
        context = capability_registry.to_synthesis_context()

        assert "Available Capabilities:" in context
        assert "http" in context
        assert "github" in context
        assert "GitHub API" in context

    def test_yaml_roundtrip(self, capability_registry: CapabilityRegistry) -> None:
        """Should save and load from YAML."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        try:
            # Save
            capability_registry.save_to_yaml(path)

            # Load into new registry
            new_registry = CapabilityRegistry()
            count = new_registry.load_from_yaml(path)

            assert count == 3
            assert new_registry.has("http")
            assert new_registry.has("github")

            # Verify auth was preserved
            github = new_registry.get("github")
            assert github is not None
            assert github.auth is not None
            assert github.auth.type == AuthType.BEARER
        finally:
            path.unlink()


class TestBuiltinCapabilities:
    """Tests for built-in capability factories."""

    def test_create_http_capability(self) -> None:
        """Should create HTTP capability with correct defaults."""
        cap = create_http_capability()

        assert cap.name == "http"
        assert cap.auth is not None
        assert cap.auth.type == AuthType.NONE
        assert "httpx" in cap.sdk_import or ""
