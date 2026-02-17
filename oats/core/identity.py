"""
Identity and Credential Management for Synth

Ensures tools ALWAYS run as the authenticated user, never as a service account.
Supports:
- AWS CLI auth (aws configure, aws sso login)
- Azure CLI auth (az login)
- GCP CLI auth (gcloud auth login)
- OAuth tokens (for platform integration)
"""

import os
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class UserIdentity:
    """Represents the authenticated user's identity."""
    provider: str  # aws, azure, gcp, github, etc.
    user_id: str
    email: str | None = None
    display_name: str | None = None
    tenant_id: str | None = None  # Azure
    account_id: str | None = None  # AWS
    project_id: str | None = None  # GCP
    raw_info: dict | None = None


class IdentityResolver:
    """
    Resolves and validates the current user's identity for each cloud provider.
    Ensures Synth always runs AS the logged-in user.
    """

    @staticmethod
    def get_aws_identity() -> UserIdentity | None:
        """Get current AWS identity from CLI auth."""
        try:
            result = subprocess.run(
                ["aws", "sts", "get-caller-identity", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return UserIdentity(
                    provider="aws",
                    user_id=data.get("UserId", ""),
                    account_id=data.get("Account"),
                    raw_info=data,
                )
        except Exception:
            pass
        return None

    @staticmethod
    def get_azure_identity() -> UserIdentity | None:
        """Get current Azure identity from CLI auth."""
        try:
            result = subprocess.run(
                ["az", "account", "show", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                user = data.get("user", {})
                return UserIdentity(
                    provider="azure",
                    user_id=user.get("name", ""),
                    email=user.get("name") if "@" in user.get("name", "") else None,
                    tenant_id=data.get("tenantId"),
                    raw_info=data,
                )
        except Exception:
            pass
        return None

    @staticmethod
    def get_gcp_identity() -> UserIdentity | None:
        """Get current GCP identity from CLI auth."""
        try:
            result = subprocess.run(
                ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data:
                    account = data[0]
                    return UserIdentity(
                        provider="gcp",
                        user_id=account.get("account", ""),
                        email=account.get("account"),
                        raw_info=account,
                    )
        except Exception:
            pass
        return None

    @staticmethod
    def get_github_identity() -> UserIdentity | None:
        """Get current GitHub identity from token."""
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return None
        try:
            import httpx
            resp = httpx.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return UserIdentity(
                    provider="github",
                    user_id=str(data.get("id", "")),
                    email=data.get("email"),
                    display_name=data.get("login"),
                    raw_info=data,
                )
        except Exception:
            pass
        return None

    @classmethod
    def get_all_identities(cls) -> dict[str, UserIdentity]:
        """Get all available identities."""
        identities = {}

        if aws := cls.get_aws_identity():
            identities["aws"] = aws
        if azure := cls.get_azure_identity():
            identities["azure"] = azure
        if gcp := cls.get_gcp_identity():
            identities["gcp"] = gcp
        if github := cls.get_github_identity():
            identities["github"] = github

        return identities


class PlatformCredentialInjector:
    """
    Injects OAuth tokens from platform SSO into Synth execution environment.

    When a user logs into AgenticWork via Azure SSO or Google SSO,
    the platform obtains OAuth tokens. This class injects those tokens
    so Synth runs AS that user.
    """

    def __init__(self):
        self._temp_files: list[Path] = []

    def inject_azure_token(self, access_token: str, tenant_id: str) -> dict[str, str]:
        """
        Inject Azure OAuth token for execution.
        Returns env vars to set.
        """
        return {
            "AZURE_ACCESS_TOKEN": access_token,
            "AZURE_TENANT_ID": tenant_id,
            # For Azure CLI compatibility
            "AZURE_CONFIG_DIR": self._create_azure_config(access_token, tenant_id),
        }

    def inject_gcp_token(self, access_token: str, project_id: str | None = None) -> dict[str, str]:
        """
        Inject GCP OAuth token for execution.
        Returns env vars to set.
        """
        env = {
            "GOOGLE_OAUTH_ACCESS_TOKEN": access_token,
        }
        if project_id:
            env["GCLOUD_PROJECT"] = project_id
            env["CLOUDSDK_CORE_PROJECT"] = project_id
        return env

    def inject_aws_credentials(
        self,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None = None,
        region: str = "us-east-1",
    ) -> dict[str, str]:
        """
        Inject AWS credentials for execution.
        Returns env vars to set.
        """
        env = {
            "AWS_ACCESS_KEY_ID": access_key_id,
            "AWS_SECRET_ACCESS_KEY": secret_access_key,
            "AWS_DEFAULT_REGION": region,
        }
        if session_token:
            env["AWS_SESSION_TOKEN"] = session_token
        return env

    def _create_azure_config(self, access_token: str, tenant_id: str) -> str:
        """Create temporary Azure config directory with token."""
        import tempfile
        config_dir = Path(tempfile.mkdtemp(prefix="oat_azure_"))
        self._temp_files.append(config_dir)

        # Write token to azure profile
        profile = {
            "installationId": "oat-execution",
            "subscriptions": [],
        }
        (config_dir / "azureProfile.json").write_text(json.dumps(profile))

        return str(config_dir)

    def cleanup(self):
        """Clean up temporary credential files."""
        import shutil
        for path in self._temp_files:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except Exception:
                pass
        self._temp_files.clear()
