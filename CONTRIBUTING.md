# Contributing to OATS

Thanks for your interest in contributing to OATS! We welcome contributions from the community.

## How to contribute

### 1. Fork the repository

Fork [agentic-work/oats](https://github.com/agentic-work/oats) to your own GitHub account.

### 2. Create a feature branch

```bash
git checkout -b feature/your-feature-name
```

### 3. Make your changes

- Follow the existing code style
- Add tests for new functionality
- Ensure all tests pass before submitting

### 4. Run the checks

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type check
mypy oats/ --ignore-missing-imports

# Lint
ruff check oats/
```

All three must pass. PRs with failing checks will not be reviewed.

### 5. Submit a Pull Request

- Open a PR against `main` from your fork
- Write a clear description of what your PR does and why
- Reference any related issues
- Keep PRs focused — one feature or fix per PR

## What we're looking for

- **New capabilities** — add built-in capabilities for services (databases, APIs, SaaS tools)
- **Bug fixes** — if you find a bug, a PR with a fix and test is the fastest path
- **Documentation** — improvements to docs, examples, or guides
- **Performance** — sandbox execution, synthesis speed, resource efficiency
- **Tests** — expanding test coverage

## Guidelines

- **Keep it simple** — OATS is designed to be minimal. Don't add complexity without clear value.
- **No credential leaks** — never put API keys, tokens, or secrets in code or tests
- **Human approval is sacred** — never bypass the HITL approval gate. Every synthesized tool must be reviewed before execution.
- **Ephemeral by design** — tools are one-shot and disposable. Don't add persistence, caching, or tool registries.
- **Provider agnostic** — contributions should work across LLM providers (Anthropic, OpenAI, Ollama, Bedrock)

## What we won't merge

- Changes that bypass human approval for tool execution
- Vendor-specific lock-in (must remain provider agnostic)
- Large dependency additions without justification
- Breaking changes to the public API without discussion first

## Code style

- Python 3.11+
- Type annotations on all public functions
- Async-first (use `async def` for I/O operations)
- `ruff` for linting, `mypy` for type checking
- No docstrings required on internal methods — keep code self-documenting

## Reporting issues

Open an issue at [github.com/agentic-work/oats/issues](https://github.com/agentic-work/oats/issues). Include:

- What you expected to happen
- What actually happened
- Steps to reproduce
- OATS version (`oats version`)
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

## AgenticWork Platform

OATS is the open-source engine behind the [AgenticWork Platform](https://agenticwork.io). If you're interested in managed OATS with OAuth credential vault, web approval UI, and server-side sandbox, check out [agenticwork.io](https://agenticwork.io).
