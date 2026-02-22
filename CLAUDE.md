# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is CLIaS?

CLIaS (CLI-as-a-Skill) observes how users interact with software (terminal commands, screenshots) and generates AI-powered CLI tools and Claude Code skills from that usage. It runs a four-layer pipeline: **Observer → Analyzer → SpecGen → CLIGen/SkillGen**.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run all tests (LLM calls are mocked)
pytest tests/ -v

# Run a single test file
pytest tests/test_api_parser.py -v

# Run a single test by name
pytest tests/ -k "test_name" -v

# Live E2E tests (requires real API key)
ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_real_e2e.py -v -s

# Lint and format
ruff check clias/
ruff format clias/
```

## Architecture

### Four-Layer Pipeline

```
Observer (record sessions)
  → Analyzer (LLM classifies commands + optional vision analysis)
    → SpecGen (build ToolSpec from patterns)
      → CLIGen (generate Click CLI) + SkillGen (generate Claude Code skill)
```

### Key modules

- **`clias/cli.py`** — Entry point. Click command group with subcommands: `observe`, `analyze`, `generate`, `skill`, `ask`, `merge`.
- **`clias/observer/`** — `ShellObserver` records commands via PTY/subprocess to JSONL. `ScreenObserver` captures screenshots with MD5-based deduplication. `Session` coordinates both.
- **`clias/analyzer/`** — `ShellAnalyzer` classifies commands via LLM (with deterministic fast-path for curl/httpie via `api_parser.py`). `VisionAnalyzer` processes screenshots with multimodal LLM. `CrossReferenceMerger` correlates UI actions with shell commands.
- **`clias/specgen/`** — `ToolSpec` (Pydantic model) is the portable intermediate representation. `SpecBuilder` transforms analyzed patterns into a ToolSpec. `APIParser` does pure-Python curl/httpie parsing. `EnvScanner` detects API key env vars without exposing values.
- **`clias/cligen/`** — `CLIScaffold` generates standalone Click-based Python scripts. `NLTranslator` maps natural language to shell commands via LLM. `Executor` runs commands with confirmation gates.
- **`clias/skillgen/`** — Generates Claude Code skill directories with `SKILL.md` frontmatter.
- **`clias/llm/`** — `LLMClient` wraps LiteLLM (provider-agnostic: Anthropic, OpenAI, Ollama). `prompts.py` contains all prompt templates.

### Data flow

`ShellEvent` (raw) → `ShellPattern` (classified) → `ToolSpec` (portable spec) → generated CLI script + skill directory

### Configuration

`clias.toml` at project root. Key settings: LLM model/temperature, screenshot interval, change threshold, output directory. Config loaded by `clias/config.py`.

## Conventions

- Python 3.11+, line length 100 (`ruff`)
- All data models use Pydantic `BaseModel` with `model_validate`/`model_dump`
- LLM responses are parsed as JSON; prompts live in `clias/llm/prompts.py`
- Tests mock LLM calls using realistic JSON response dicts (see `MOCK_CLASSIFY_RESPONSES` in test files)
- API call detection (curl/httpie) uses deterministic parsing, not LLM
- Credentials are never stored; detected from env vars and prompted interactively
