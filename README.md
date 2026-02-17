<p align="center">
  <img src="https://storage.googleapis.com/agenticwork-cdn/oats/oats-banner.png" alt="OATS — On-demand Agent Tool Synthesis" />
</p>

<p align="center">
  <strong>LLMs don't pick from a menu. They cook what they need.</strong>
</p>

<p align="center">
  <a href="https://github.com/agentic-work/oats/actions"><img src="https://img.shields.io/github/actions/workflow/status/agentic-work/oats/ci.yml?style=flat-square&label=CI" alt="CI" /></a>
  <a href="https://pypi.org/project/oats-ai/"><img src="https://img.shields.io/pypi/v/oats-ai?style=flat-square&color=%2366e5a6" alt="PyPI" /></a>
  <a href="https://github.com/agentic-work/oats/blob/main/LICENSE"><img src="https://img.shields.io/github/license/agentic-work/oats?style=flat-square" alt="MIT License" /></a>
  <a href="https://github.com/agentic-work/oats/stargazers"><img src="https://img.shields.io/github/stars/agentic-work/oats?style=flat-square&color=f2a659" alt="Stars" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square" alt="Python 3.11+" />
</p>

<p align="center">
  <a href="https://oats.agenticwork.io">Website</a> &bull;
  <a href="https://oats-docs.agenticwork.io">Docs</a> &bull;
  <a href="https://oats-docs.agenticwork.io/getting-started/installation">Getting Started</a> &bull;
  <a href="https://agenticwork.io">AgenticWork Platform</a> &bull;
  <a href="https://github.com/agentic-work/oats/discussions">Discussions</a>
</p>

---

## What is OATS?

**OATS** lets LLMs synthesize tools on-the-fly instead of relying on pre-built tool libraries. No MCP server to install. No schema to maintain. The LLM writes exactly the tool it needs, a human approves it, and it runs.

```
"List my GCS buckets and their sizes"

→ OATS synthesizes a Python function that calls the GCP Storage API
→ You see the code and approve
→ Returns: 10 buckets, 6.25 GB total, with sizes, locations, and creation dates
```

No one pre-built that tool. No MCP server was installed. The LLM wrote it in 2 seconds from a natural language request.

---

## Two ways to use OATS

### 1. Self-hosted (open source)

Install the engine, manage your own credentials, run locally or in your infrastructure.

```bash
pip install oats-ai
oats synth "list all S3 buckets in my AWS account"
```

You handle credential setup (API keys, env vars, service accounts). Full control, full flexibility. Great for developers and infrastructure teams.

### 2. AgenticWork Platform (managed)

**Connect your accounts. Approve or deny. That's it.**

The [AgenticWork Platform](https://agenticwork.io) runs OATS as a managed service with:

- **One-click OAuth connections** — connect GitHub, AWS, GCP, Azure, Slack, Jira, and more through your browser. No API keys. No env vars. No terminal.
- **Credential vault** — tokens stored encrypted, scoped per-user, automatically rotated.
- **Web approval UI** — see what the tool will do, approve or deny with one click.
- **Server-side sandbox** — execution happens in isolated containers on managed infrastructure.
- **Team access controls** — share capabilities across your org with role-based permissions.
- **Audit log** — every synthesis, approval, and execution is logged.

The platform handles the plumbing so you just say what you need and approve the result.

<p align="center">
  <a href="https://agenticwork.io"><strong>Try the AgenticWork Platform →</strong></a>
</p>

---

## What can OATS do?

OATS replaces the need to find, install, and configure individual MCP servers or tool integrations. Some examples:

| Instead of installing... | Just say... |
|--------------------------|-------------|
| A GitHub MCP server | "show my open PRs with failing CI checks" |
| An AWS cost tool | "get my AWS spending for the last 30 days by service" |
| A GCP storage client | "list all GCS buckets and their sizes" |
| A Jira integration | "find all overdue tickets assigned to me" |
| A Slack bot | "post a summary of today's deploys to #engineering" |
| A weather API wrapper | "get the 5-day forecast for NYC" |
| A database query tool | "find users who signed up this week but haven't logged in" |

With the self-hosted engine, you configure credentials yourself. With the [AgenticWork Platform](https://agenticwork.io), you connect your accounts once and just approve.

---

## Quick start (self-hosted)

```bash
pip install oats-ai
```

### Use with Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "oats": {
      "command": "oats",
      "args": ["mcp", "serve"],
      "env": {
        "SYNTH_PROVIDER": "anthropic",
        "SYNTH_MODEL": "claude-sonnet-4-20250514",
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

### Use from the CLI

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Synthesize, approve, execute
oats synth "list all GCS buckets in my project with their sizes"

# Dry run — see the synthesized code without executing
oats synth "get my AWS bill for this month" --dry-run --show-code

# Use a different LLM provider
oats synth "find open GitHub issues labeled bug" --provider ollama --model llama3.2
```

### Use as a Python library

```python
import asyncio
from oats import CapabilityRegistry, Synthesizer, Executor, HITLGate
from oats.core.llm import create_llm_client
from oats.hitl import CLIApprovalHandler

async def main():
    registry = CapabilityRegistry()
    registry.register_builtin("http", "github", "aws", "gcp")

    client = create_llm_client("anthropic", api_key="sk-ant-...")
    synthesizer = Synthesizer(llm_client=client, capability_registry=registry)
    tool = await synthesizer.synthesize("get my AWS costs for the last 7 days by service")

    gate = HITLGate(handler=CLIApprovalHandler())
    decision = await gate.submit_for_approval(tool)

    if decision.approved:
        output = await Executor().execute(tool)
        print(output.result)

asyncio.run(main())
```

---

## Built-in capabilities

| Capability | What it provides |
|-----------|-----------------|
| `http` | HTTP requests to any API |
| `github` | GitHub REST API — repos, issues, PRs, notifications |
| `slack` | Slack Web API — messages, channels, users |
| `aws` | AWS via boto3 — S3, DynamoDB, Lambda, SQS, SNS, CloudWatch, EC2, Cost Explorer |
| `gcp` | Google Cloud — Storage, BigQuery, Pub/Sub, Compute Engine, Billing |
| `azure` | Microsoft Azure — Blob Storage, Cosmos DB, Key Vault, Functions |
| `filesystem` | Read/write local files |
| `shell` | Run shell commands |
| `json` | Parse/transform JSON |
| `datetime` | Date/time operations |
| `data` | Data processing (sort, filter, aggregate) |

Define your own capabilities in YAML for internal APIs, databases, or any service. See the [Custom Capabilities guide](https://oats-docs.agenticwork.io/guides/custom-capabilities).

---

## How it works

```
Intent → Capabilities → LLM Synthesizer → Human Approval → Sandbox Execution
```

1. You describe what you want in natural language
2. OATS checks what capabilities (APIs, services, credentials) are available
3. The LLM writes an async Python function tailored to your request
4. You review the code, risk level, and explanation — then approve or deny
5. Approved tools execute in an isolated sandbox with scoped credentials
6. Tools are discarded after use. No schema debt. No zombie tools.

---

## Supported LLM providers

| Provider | Config |
|----------|--------|
| Anthropic | `SYNTH_PROVIDER=anthropic` |
| OpenAI | `SYNTH_PROVIDER=openai SYNTH_BASE_URL=https://api.openai.com` |
| AWS Bedrock | `SYNTH_PROVIDER=bedrock AWS_REGION=us-east-1` |
| Ollama (local) | `SYNTH_PROVIDER=ollama SYNTH_MODEL=llama3.2` |
| Any OpenAI-compatible | `SYNTH_PROVIDER=openai SYNTH_BASE_URL=https://your-api.com` |

---

## Contributing

```bash
git clone https://github.com/agentic-work/oats.git
cd oats
pip install -e ".[dev]"

pytest                          # Run tests
mypy oats/ --ignore-missing-imports  # Type check
ruff check oats/                # Lint
```

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  <strong>OATS</strong> — On-demand Agent Tool Synthesis<br />
  <sub>The open-source engine behind <a href="https://agenticwork.io">AgenticWork</a></sub>
</p>
