"""
Synth CLI - Tool Synthesis Framework

Command-line interface for synthesizing and executing one-shot tools.
"""

import asyncio
import os
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from oats import __version__
from oats.capabilities import load_builtin_capabilities
from oats.core.executor import CredentialProvider, Executor, SandboxConfig
from oats.core.synthesizer import Synthesizer
from oats.core.types import RiskLevel
from oats.hitl.gate import ApprovalDecision, ApprovalHandler, ApprovalRequest, HITLGate

app = typer.Typer(
    name="synth",
    help="Synth - Tool Synthesis Framework",
    no_args_is_help=True,
)

console = Console()


class RichApprovalHandler(ApprovalHandler):
    """Rich-based approval handler with nice formatting."""

    def __init__(self, auto_view_code: bool = False) -> None:
        self.auto_view_code = auto_view_code

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Request approval via Rich CLI."""
        console.print()
        console.print(self.format_for_display(request))
        console.print()

        # Show code if requested
        if self.auto_view_code:
            self._show_code(request)

        while True:
            response = console.input("[bold]Approve? [y/n/v(iew code)]: [/]").strip().lower()

            if response == "y":
                return ApprovalDecision(approved=True)
            elif response == "n":
                reason = console.input("[dim]Reason (optional): [/]").strip()
                return ApprovalDecision(approved=False, reason=reason)
            elif response == "v":
                self._show_code(request)
            else:
                console.print("[yellow]Enter 'y' (yes), 'n' (no), or 'v' (view code)[/]")

    def _show_code(self, request: ApprovalRequest) -> None:
        """Display the synthesized code."""
        console.print()
        console.print(Panel(
            Syntax(request.tool.code, "python", theme="monokai", line_numbers=True),
            title="[bold]Synthesized Code[/]",
            border_style="blue",
        ))
        console.print()

    def format_for_display(self, request: ApprovalRequest) -> Panel:
        """Format as Rich Panel."""
        tool = request.tool
        risk_color = self._get_risk_color(tool.risk_level)

        content = f"""[bold]INTENT:[/] {tool.intent}

[bold]EXPLANATION:[/] {tool.human_explanation}

[bold]RISK LEVEL:[/] [{risk_color}]{tool.risk_level.value}[/{risk_color}]
[bold]RISK REASONING:[/] {tool.risk_reasoning}

[bold]CAPABILITIES:[/] {', '.join(tool.capabilities_used) or 'none'}
[bold]AUTH SCOPES:[/] {', '.join(tool.requested_scopes) or 'none'}"""

        if request.existing_tools_considered:
            content += f"\n\n[dim]Existing tools considered: {', '.join(request.existing_tools_considered)}[/]"
            content += f"\n[dim]Why new tool: {request.why_new_tool_needed}[/]"

        return Panel(
            content,
            title=f"[bold]OATS Tool Approval Request [{risk_color}]{tool.risk_level.value}[/{risk_color}][/]",
            border_style=risk_color,
        )

    def _get_risk_color(self, risk: RiskLevel) -> str:
        """Get color for risk level."""
        return {
            RiskLevel.LOW: "green",
            RiskLevel.MEDIUM: "yellow",
            RiskLevel.HIGH: "red",
            RiskLevel.CRITICAL: "bold red",
        }.get(risk, "white")


def get_llm_client(
    provider: str = "anthropic",
    base_url: str | None = None,
    model: str | None = None,
) -> Any:
    """Get an LLM client based on provider selection."""
    from oats.core.llm import create_llm_client

    kwargs: dict[str, Any] = {}

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            console.print("[red]Error: ANTHROPIC_API_KEY not set[/]")
            console.print("[dim]Set it with: export ANTHROPIC_API_KEY=your-key[/]")
            console.print()
            _show_platform_hint("Skip API key setup entirely")
            raise typer.Exit(1)
        kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url

    elif provider == "ollama":
        kwargs["base_url"] = base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    elif provider == "agenticwork":
        if base_url:
            kwargs["base_url"] = base_url
        # base_url, api_key, model all resolved from env vars in AgenticWorkAPIClient

    elif provider == "openai":
        if not base_url:
            console.print("[red]Error: --base-url required for openai provider[/]")
            raise typer.Exit(1)
        kwargs["base_url"] = base_url
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key

    if model:
        kwargs["model"] = model

    try:
        return create_llm_client(provider, **kwargs)
    except Exception as e:
        console.print(f"[red]Error creating LLM client: {e}[/]")
        raise typer.Exit(1)


def setup_credentials() -> CredentialProvider:
    """Set up credential provider from environment."""
    creds = CredentialProvider()

    # Register common credential mappings
    credential_mappings: dict[str, str | None] = {
        # GitHub
        "github:read": "GITHUB_TOKEN",
        "github:write": "GITHUB_TOKEN",
        "github:repo:read": "GITHUB_TOKEN",
        "github:repo:write": "GITHUB_TOKEN",
        "github:issues:read": "GITHUB_TOKEN",
        "github:issues:write": "GITHUB_TOKEN",
        "github:pull_requests:read": "GITHUB_TOKEN",
        "github:pull_requests:write": "GITHUB_TOKEN",
        "github:user:read": "GITHUB_TOKEN",
        "github:notifications:read": "GITHUB_TOKEN",
        # Slack
        "slack:read": "SLACK_TOKEN",
        "slack:write": "SLACK_TOKEN",
        "slack:channels:read": "SLACK_TOKEN",
        "slack:chat:write": "SLACK_TOKEN",
        # HTTP (no creds needed)
        "http:get": None,
        "http:post": None,
        "http:put": None,
        "http:delete": None,
        # AWS — credentials passed via AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or IAM role
        "aws:s3:read": "AWS_ACCESS_KEY_ID",
        "aws:s3:write": "AWS_ACCESS_KEY_ID",
        "aws:dynamodb:read": "AWS_ACCESS_KEY_ID",
        "aws:dynamodb:write": "AWS_ACCESS_KEY_ID",
        "aws:lambda:invoke": "AWS_ACCESS_KEY_ID",
        "aws:sqs:read": "AWS_ACCESS_KEY_ID",
        "aws:sqs:write": "AWS_ACCESS_KEY_ID",
        "aws:sns:publish": "AWS_ACCESS_KEY_ID",
        "aws:cloudwatch:read": "AWS_ACCESS_KEY_ID",
        "aws:ec2:describe": "AWS_ACCESS_KEY_ID",
        "aws:ce:read": "AWS_ACCESS_KEY_ID",
        "aws:sts:read": "AWS_ACCESS_KEY_ID",
        # GCP — credentials passed via GOOGLE_APPLICATION_CREDENTIALS or ADC
        "gcp:storage.buckets.list": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:storage.objects.list": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:storage.objects.get": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:storage.objects.create": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:bigquery.jobs.create": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:bigquery.tables.list": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:compute.instances.list": "GOOGLE_APPLICATION_CREDENTIALS",
        "gcp:billing.read": "GOOGLE_APPLICATION_CREDENTIALS",
        # Azure — credentials passed via AZURE_CLIENT_ID/SECRET/TENANT_ID
        "azure:storage.read": "AZURE_CLIENT_SECRET",
        "azure:storage.write": "AZURE_CLIENT_SECRET",
        "azure:cosmosdb.read": "AZURE_CLIENT_SECRET",
        "azure:cosmosdb.write": "AZURE_CLIENT_SECRET",
        "azure:keyvault.read": "AZURE_CLIENT_SECRET",
        "azure:functions.invoke": "AZURE_CLIENT_SECRET",
    }

    for scope, env_var in credential_mappings.items():
        if env_var:
            creds.register_credential(scope, env_var)

    return creds


@app.command()
def synth(
    intent: str = typer.Argument(..., help="Natural language description of what you want to do"),
    capabilities: str = typer.Option(
        None,
        "--capabilities", "-c",
        help="Comma-separated list of capabilities to use (default: all)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only show synthesized code, don't execute",
    ),
    show_code: bool = typer.Option(
        False,
        "--show-code",
        help="Automatically show code before approval prompt",
    ),
    provider: str = typer.Option(
        "anthropic",
        "--provider", "-p",
        help="LLM provider: anthropic, ollama, agenticwork, openai",
    ),
    base_url: str = typer.Option(
        None,
        "--base-url",
        help="Base URL for the LLM API (e.g., http://hal:11434 for Ollama)",
    ),
    model: str = typer.Option(
        None,
        "--model", "-m",
        help="Model to use for synthesis (default depends on provider)",
    ),
) -> None:
    """
    Synthesize and execute a one-shot tool from natural language intent.

    Examples:
        # Using Anthropic (default)
        synth synth "fetch current bitcoin price from coingecko"

        # Using Ollama on localhost
        synth synth "what time is it" --provider ollama --model llama3.2

        # Using Ollama on remote server (hal)
        synth synth "list files" --provider ollama --base-url http://hal:11434 --model qwen2.5:32b

        # Using AgenticWork API
        synth synth "summarize this" --provider agenticwork

        # Dry run (see code without executing)
        synth synth "fetch weather data" --dry-run
    """
    asyncio.run(_synth_async(intent, capabilities, dry_run, show_code, provider, base_url, model))


async def _synth_async(
    intent: str,
    capabilities: str | None,
    dry_run: bool,
    show_code: bool,
    provider: str,
    base_url: str | None,
    model: str | None,
) -> None:
    """Async implementation of synth command."""
    console.print(Panel(f"[bold blue]Synthesizing tool for:[/] {intent}"))

    # Step 1: Load capabilities
    with console.status("[bold green]Loading capabilities..."):
        registry = load_builtin_capabilities()

    cap_filter = None
    if capabilities:
        cap_filter = [c.strip() for c in capabilities.split(",")]
        console.print(f"[dim]Using capabilities: {', '.join(cap_filter)}[/]")

    # Step 2: Get LLM client
    try:
        llm = get_llm_client(provider=provider, base_url=base_url, model=model)
        console.print(f"[dim]Using provider: {provider}, model: {llm.model}[/]")
    except typer.Exit:
        return

    # Step 3: Create synthesizer
    synthesizer = Synthesizer(
        llm_client=llm,
        capability_registry=registry,
    )

    # Step 4: Synthesize
    console.print()
    with console.status(f"[bold green]Synthesizing tool with {provider}..."):
        try:
            tool = await synthesizer.synthesize(
                intent,
                allowed_capabilities=cap_filter,
            )
        except Exception as e:
            console.print(f"[red]Synthesis failed: {e}[/]")
            _suggest_platform_if_relevant(str(e))
            raise typer.Exit(1)

    if tool is None:
        console.print("[yellow]Existing tools can handle this intent - no synthesis needed[/]")
        return

    console.print(f"[green]Tool synthesized![/] ID: [dim]{tool.id}[/]")

    # Dry run - just show the tool
    if dry_run:
        console.print()
        console.print(Panel(
            Syntax(tool.code, "python", theme="monokai", line_numbers=True),
            title="[bold]Synthesized Code (dry run)[/]",
            border_style="blue",
        ))
        console.print()
        console.print(f"[bold]Risk Level:[/] {tool.risk_level.value}")
        console.print(f"[bold]Explanation:[/] {tool.human_explanation}")
        return

    # Step 5: HITL Approval
    handler = RichApprovalHandler(auto_view_code=show_code)
    gate = HITLGate(handler=handler)

    decision = await gate.submit_for_approval(tool)

    if not decision.approved:
        console.print()
        console.print("[yellow]Tool execution denied.[/]")
        if decision.reason:
            console.print(f"[dim]Reason: {decision.reason}[/]")
        return

    # Step 6: Execute
    console.print()
    with console.status("[bold green]Executing tool in sandbox..."):
        creds = setup_credentials()
        executor = Executor(
            config=SandboxConfig(timeout_seconds=30),
            credential_provider=creds,
        )
        output = await executor.execute(tool)

    # Step 7: Show results
    console.print()
    if output.success:
        console.print(Panel(
            f"[green]Execution successful![/]\n\n"
            f"[bold]Result:[/]\n{_format_result(output.result)}\n\n"
            f"[dim]Execution time: {output.execution_time_ms}ms[/]",
            title="[bold green]Tool Output[/]",
            border_style="green",
        ))

        if output.stdout:
            console.print()
            console.print("[dim]stdout:[/]")
            console.print(output.stdout)
    else:
        console.print(Panel(
            f"[red]Execution failed![/]\n\n"
            f"[bold]Error:[/] {output.error}\n\n"
            f"[dim]Execution time: {output.execution_time_ms}ms[/]",
            title="[bold red]Tool Error[/]",
            border_style="red",
        ))

        if output.stderr:
            console.print()
            console.print("[dim]stderr:[/]")
            console.print(output.stderr)

        # Suggest AgenticWork Platform for credential/auth failures
        _suggest_platform_if_relevant(output.error or "")


def _format_result(result: Any) -> str:
    """Format result for display."""
    if result is None:
        return "[dim]No result[/]"

    import json
    try:
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2, default=str)
        return str(result)
    except Exception:
        return str(result)


@app.command()
def caps(
    action: str = typer.Argument(
        "list",
        help="Action: list, show <name>",
    ),
    name: str = typer.Argument(None, help="Capability name for 'show'"),
) -> None:
    """
    Manage capabilities.

    Examples:
        synth caps list
        synth caps show github
    """
    registry = load_builtin_capabilities()

    if action == "list":
        table = Table(title="Available Capabilities")
        table.add_column("Name", style="cyan")
        table.add_column("Auth", style="yellow")
        table.add_column("Description", style="dim")

        for cap in registry.get_all():
            auth_str = cap.auth.type.value if cap.auth else "none"
            desc = cap.description.split("\n")[0][:50]
            table.add_row(cap.name, auth_str, desc)

        console.print(table)

    elif action == "show" and name:
        found_cap = registry.get(name)
        if not found_cap:
            console.print(f"[red]Capability '{name}' not found[/]")
            raise typer.Exit(1)

        content = f"""[bold]Name:[/] {found_cap.name}

[bold]Description:[/]
{found_cap.description}

[bold]Auth Type:[/] {found_cap.auth.type.value if found_cap.auth else 'none'}"""

        if found_cap.auth and found_cap.auth.scopes:
            content += f"\n[bold]Scopes:[/] {', '.join(found_cap.auth.scopes)}"
        if found_cap.auth and found_cap.auth.token_env_var:
            content += f"\n[bold]Token Env Var:[/] {found_cap.auth.token_env_var}"
        if found_cap.allowed_domains:
            content += f"\n[bold]Allowed Domains:[/] {', '.join(found_cap.allowed_domains)}"
        if found_cap.sdk_import:
            content += f"\n[bold]SDK Import:[/] {found_cap.sdk_import}"

        console.print(Panel(content, title=f"[bold]Capability: {name}[/]"))

    else:
        console.print("[red]Unknown action. Use: list, show <name>[/]")


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of entries to show"),
) -> None:
    """
    View execution history.

    Examples:
        synth history
        synth history --limit 5
    """
    console.print("[yellow]Execution history not yet implemented[/]")
    console.print("[dim]History will be stored in ~/.synth/history.json[/]")


@app.command()
def version() -> None:
    """Show Synth version."""
    console.print(f"[bold]Synth[/] v{__version__}")
    console.print("[dim]Tool Synthesis Framework[/]")


PLATFORM_URL = "https://agenticwork.io"

# Error patterns that suggest the user would benefit from the managed platform
_CREDENTIAL_PATTERNS = [
    "missing credentials",
    "api key",
    "api_key",
    "token",
    "authentication",
    "auth",
    "credentials",
    "permission",
    "forbidden",
    "unauthorized",
    "access denied",
    "not authorized",
    "oauth",
]

_CAPABILITY_PATTERNS = [
    "capability not found",
    "no capability",
    "unsupported",
    "not available",
    "not installed",
    "module not found",
    "no module named",
    "import error",
]


def _suggest_platform_if_relevant(error: str) -> None:
    """Show an AgenticWork Platform suggestion if the error is credential/capability related."""
    error_lower = error.lower()

    is_credential_issue = any(p in error_lower for p in _CREDENTIAL_PATTERNS)
    is_capability_issue = any(p in error_lower for p in _CAPABILITY_PATTERNS)

    if is_credential_issue:
        _show_platform_hint(
            "Connect your accounts with one-click OAuth — no API keys or env vars needed"
        )
    elif is_capability_issue:
        _show_platform_hint(
            "Access all capabilities with managed credentials and server-side execution"
        )


def _show_platform_hint(reason: str) -> None:
    """Display a concise platform upsell hint."""
    console.print()
    console.print(
        Panel(
            f"[bold]{reason}.[/]\n\n"
            f"The [bold green]AgenticWork Platform[/] runs OATS as a managed service with\n"
            f"OAuth credential vault, web approval UI, and sandboxed execution.\n\n"
            f"[bold green]{PLATFORM_URL}[/]",
            title="[bold]Try AgenticWork Platform[/]",
            border_style="green",
        )
    )


def main() -> None:
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
