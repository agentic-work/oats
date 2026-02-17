"""
Capability Registry

Manages available capabilities that synthesized tools can use.
This is the key inversion from traditional tool registries:
we register CAPABILITIES (what's available), not TOOLS (how to use it).
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import yaml

from oats.core.types import AuthType, Capability, CapabilityAuth


class CapabilityRegistry:
    """
    Registry of capabilities available for tool synthesis.

    Capabilities describe available resources/APIs. The LLM uses these
    to understand what it CAN access when synthesizing tools.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a capability."""
        self._capabilities[capability.name] = capability

    def register_many(self, capabilities: list[Capability]) -> None:
        """Register multiple capabilities."""
        for cap in capabilities:
            self.register(cap)

    def register_builtin(self, *names: str) -> None:
        """Register one or more built-in capabilities by name."""
        builtin_factories: dict[str, Callable[[], Capability]] = {
            "http": create_http_capability,
            "filesystem": create_filesystem_capability,
        }
        # Simple built-ins that don't need factory functions
        simple_builtins: dict[str, str] = {
            "json": "Parse and transform JSON data",
            "datetime": "Date/time operations and formatting",
            "data": "Data processing and analysis",
            "shell": "Execute shell commands (with restrictions)",
            "github": "Access GitHub API for repos, issues, PRs, notifications",
            "slack": "Access Slack API for messaging and channels",
            "aws": "Access AWS services via boto3 (S3, DynamoDB, Lambda, SQS, etc.)",
            "gcp": "Access Google Cloud Platform services (Storage, BigQuery, Pub/Sub, etc.)",
            "azure": "Access Microsoft Azure services (Blob Storage, Cosmos DB, Key Vault, etc.)",
        }
        for name in names:
            if name in builtin_factories:
                self.register(builtin_factories[name]())
            elif name in simple_builtins:
                self.register(Capability(
                    name=name,
                    description=simple_builtins[name],
                ))
            else:
                raise KeyError(f"Unknown built-in capability: {name}. Available: {sorted(list(builtin_factories) + list(simple_builtins))}")

    def get(self, name: str) -> Capability | None:
        """Get a capability by name."""
        return self._capabilities.get(name)

    def get_all(self) -> list[Capability]:
        """Get all registered capabilities."""
        return list(self._capabilities.values())

    # Alias for docs compatibility
    list_all = get_all

    def get_names(self) -> list[str]:
        """Get all capability names."""
        return list(self._capabilities.keys())

    def has(self, name: str) -> bool:
        """Check if a capability exists."""
        return name in self._capabilities

    def remove(self, name: str) -> bool:
        """Remove a capability. Returns True if it existed."""
        if name in self._capabilities:
            del self._capabilities[name]
            return True
        return False

    def clear(self) -> None:
        """Remove all capabilities."""
        self._capabilities.clear()

    def __len__(self) -> int:
        return len(self._capabilities)

    def __iter__(self) -> Iterator[Capability]:
        return iter(self._capabilities.values())

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def get_scopes_for_capability(self, name: str) -> list[str]:
        """Get available auth scopes for a capability."""
        cap = self.get(name)
        if cap and cap.auth:
            return cap.auth.scopes
        return []

    def filter_by_auth_type(self, auth_type: AuthType) -> list[Capability]:
        """Get capabilities with a specific auth type."""
        return [
            cap for cap in self._capabilities.values()
            if cap.auth and cap.auth.type == auth_type
        ]

    def to_synthesis_context(self) -> str:
        """
        Generate a context string for the synthesizer.

        This is what the LLM sees when deciding what capabilities to use.
        """
        lines = ["Available Capabilities:"]
        lines.append("=" * 40)

        for cap in self._capabilities.values():
            lines.append(f"\n## {cap.name}")
            lines.append(f"Description: {cap.description}")

            if cap.auth:
                lines.append(f"Auth: {cap.auth.type.value}")
                if cap.auth.scopes:
                    lines.append(f"Scopes: {', '.join(cap.auth.scopes)}")

            if cap.allowed_domains:
                lines.append(f"Allowed domains: {', '.join(cap.allowed_domains)}")

            if cap.sdk_import:
                lines.append(f"SDK: {cap.sdk_import}")

            if cap.sdk_hints:
                lines.append(f"Hints: {cap.sdk_hints}")

            if cap.schema_url:
                lines.append(f"Schema: {cap.schema_url}")

        return "\n".join(lines)

    def load_from_yaml(self, path: Path) -> int:
        """
        Load capabilities from a YAML file.

        Returns the number of capabilities loaded.
        """
        with open(path) as f:
            data = yaml.safe_load(f)

        count = 0
        for cap_data in data.get("capabilities", []):
            # Parse auth if present
            auth = None
            if "auth" in cap_data:
                auth_data = cap_data["auth"]
                auth = CapabilityAuth(
                    type=AuthType(auth_data.get("type", "none")),
                    scopes=auth_data.get("scopes", []),
                    token_env_var=auth_data.get("token_env_var"),
                    description=auth_data.get("description", ""),
                    header_name=auth_data.get("header_name"),
                    header_prefix=auth_data.get("header_prefix"),
                )

            cap = Capability(
                name=cap_data["name"],
                description=cap_data.get("description", ""),
                auth=auth,
                allowed_domains=cap_data.get("allowed_domains", []),
                rate_limit=cap_data.get("rate_limit"),
                max_response_size=cap_data.get("max_response_size", 1_000_000),
                schema_url=cap_data.get("schema_url"),
                schema_type=cap_data.get("schema_type"),
                sdk_package=cap_data.get("sdk_package"),
                sdk_import=cap_data.get("sdk_import"),
                sdk_hints=cap_data.get("sdk_hints"),
            )
            self.register(cap)
            count += 1

        return count

    # Alias for docs compatibility
    load_yaml = load_from_yaml

    def save_to_yaml(self, path: Path) -> None:
        """Save capabilities to a YAML file."""
        caps_data = []
        for cap in self._capabilities.values():
            cap_dict: dict = {
                "name": cap.name,
                "description": cap.description,
            }

            if cap.auth:
                cap_dict["auth"] = {
                    "type": cap.auth.type.value,
                    "scopes": cap.auth.scopes,
                }
                if cap.auth.token_env_var:
                    cap_dict["auth"]["token_env_var"] = cap.auth.token_env_var
                if cap.auth.description:
                    cap_dict["auth"]["description"] = cap.auth.description

            if cap.allowed_domains:
                cap_dict["allowed_domains"] = cap.allowed_domains
            if cap.rate_limit:
                cap_dict["rate_limit"] = cap.rate_limit
            if cap.schema_url:
                cap_dict["schema_url"] = cap.schema_url
            if cap.schema_type:
                cap_dict["schema_type"] = cap.schema_type
            if cap.sdk_package:
                cap_dict["sdk_package"] = cap.sdk_package
            if cap.sdk_import:
                cap_dict["sdk_import"] = cap.sdk_import
            if cap.sdk_hints:
                cap_dict["sdk_hints"] = cap.sdk_hints

            caps_data.append(cap_dict)

        with open(path, "w") as f:
            yaml.dump({"capabilities": caps_data}, f, default_flow_style=False)


# Built-in capabilities that are commonly needed
def create_http_capability() -> Capability:
    """Create a basic HTTP capability."""
    return Capability(
        name="http",
        description="Make HTTP requests to allowed domains",
        auth=CapabilityAuth(
            type=AuthType.NONE,
            description="No auth required, but domain restrictions apply",
        ),
        allowed_domains=[],  # Must be configured
        sdk_import="import httpx",
    )


def create_filesystem_capability(base_path: str = ".") -> Capability:
    """Create a filesystem capability with path restrictions."""
    return Capability(
        name="filesystem",
        description=f"Read/write files within {base_path}",
        auth=CapabilityAuth(
            type=AuthType.NONE,
            description="No auth, but path restrictions apply",
        ),
        sdk_import="from pathlib import Path",
    )
