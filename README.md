# CLIaS — CLI as a Service

Turn any observed software into an AI-powered command-line assistant.

CLIaS watches how software is used (terminal commands and optionally GUI interactions), distills that knowledge into a structured specification, then generates a custom CLI where users describe what they want in **natural language** and an LLM translates it into the correct shell commands.

```
┌──────────┐   ┌───────────┐   ┌──────────┐   ┌──────────────────┐
│ Observer  │──▶│ Analyzer  │──▶│ SpecGen  │──▶│ CLIGen + SkillGen│
│  Layer    │   │  Engine   │   │          │   │                  │
└──────────┘   └───────────┘   └──────────┘   └──────────────────┘
     │                                             │
     ▼                                             ▼
Screen + Shell                               Generated CLI +
recordings                                   Claude Code Skill
```

## Quick Start

### 1. Install

```bash
# From source (development mode)
git clone https://github.com/SecchiAlessandro/CLIaS.git
cd CLIaS
pip install -e ".[dev]"

# Verify
clias --version
```

### 2. Set up your LLM provider

CLIaS uses [LiteLLM](https://docs.litellm.ai/) under the hood, so it works with any supported provider.

| Provider | Environment variable | Model config |
|----------|---------------------|--------------|
| **OpenAI** | `OPENAI_API_KEY` | `model = "gpt-4o"` (default) |
| **Anthropic** | `ANTHROPIC_API_KEY` | `model = "anthropic/claude-sonnet-4-20250514"` |
| **Ollama** (local) | — | `model = "ollama/llama3"` |

```bash
# Example: Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Record, Analyze, Generate, Ask

```bash
# Step 1 — Observe: record a git session
clias observe -C "git status" -C "git log --oneline -5" -C "git branch -a"

# Step 2 — Analyze: turn recordings into a ToolSpec
clias analyze ./clias_sessions/session_* -o git_spec.json

# Step 3 — Generate: produce a standalone CLI
clias generate git_spec.json -o git_cli.py

# Step 4 — Ask: use natural language
clias ask git_spec.json "show me the last 10 commits"
```

## Commands

### `clias observe`

Record a shell session (and optionally the screen) for later analysis.

```bash
# Run specific commands
clias observe -C "docker ps" -C "docker images" -o ./my_session

# Interactive mode — spawns a shell, records everything until you exit
clias observe -o ./my_session

# With screenshot capture (requires a display server)
clias observe --screen -C "git diff"
```

| Option | Description |
|--------|-------------|
| `-o, --output` | Output directory (default: `./clias_sessions`) |
| `--screen` | Also capture screenshots |
| `-C, --command` | Run a specific command (repeatable) |

**Output:** a session directory containing `manifest.json`, `shell_events.jsonl`, and optionally `screenshots/`.

### `clias analyze`

Process a recorded session into a ToolSpec using LLM-based classification.

```bash
clias analyze ./clias_sessions/session_20260219_120000 -o git_spec.json

# YAML output
clias analyze ./session_dir -o spec.yaml --format yaml

# Include screenshot analysis (multimodal LLM)
clias analyze ./session_dir --vision
```

| Option | Description |
|--------|-------------|
| `-o, --output` | Output spec path (default: `<session_dir>/tool_spec.json`) |
| `--format` | `json` or `yaml` (default: `json`) |
| `--vision / --no-vision` | Include screenshot analysis (default: off) |
| `--no-prompt` | Disable interactive credential prompting |
| `--no-generate` | Skip automatic CLI and skill generation |
| `--skills-dir` | Directory for generated skills (default: `./skills`) |

**Pipeline:** Load events → Classify commands (with deterministic fast-path for curl/httpie) → (optional) Analyze screenshots → Cross-reference → Build ToolSpec → Auto-generate CLI + Claude Code skill.

### `clias generate`

Produce a standalone, executable Python CLI from a ToolSpec.

```bash
clias generate git_spec.json -o git_cli.py

# Then use it
python git_cli.py --help
python git_cli.py ask "create a new feature branch"
```

| Option | Description |
|--------|-------------|
| `-o, --output` | Output script path (default: `./<tool_name>_cli.py`) |
| `--skill / --no-skill` | Also generate a Claude Code skill (default: on) |
| `--skills-dir` | Directory for generated skills (default: `./skills`) |

The generated CLI includes:
- Click command groups organized by capability
- An `ask` subcommand for natural language interaction
- Embedded ToolSpec as a JSON constant (fully portable)

### `clias skill`

Generate a Claude Code skill directory from an existing ToolSpec. The skill includes a `SKILL.md` with frontmatter, reference docs, and scripts.

```bash
# Generate skill from spec (auto-generates CLI script if not provided)
clias skill git_spec.json -o ./skills

# Use an existing CLI script
clias skill git_spec.json --cli-script git_cli.py -o ./skills
```

| Option | Description |
|--------|-------------|
| `--cli-script` | Path to an existing CLI script (generates one if omitted) |
| `-o, --output` | Skills output directory (default: `./skills`) |

### `clias ask`

One-shot natural language to command translation using an existing spec.

```bash
# Propose commands (with confirmation prompt)
clias ask git_spec.json "show me recent commits on the main branch"

# Execute immediately (skip confirmation)
clias ask git_spec.json "list all remote branches" --execute

# Dry run — show commands only
clias ask git_spec.json "undo last commit" --dry-run
```

| Option | Description |
|--------|-------------|
| `-x, --execute` | Execute immediately without confirmation |
| `-n, --dry-run` | Show commands only, don't execute |

### `clias merge`

Combine multiple ToolSpec files into one (deduplicates by canonical command name).

```bash
clias merge spec_session1.json spec_session2.json -o merged_spec.json
clias merge *.yaml -o full_spec.yaml --format yaml
```

| Option | Description |
|--------|-------------|
| `-o, --output` | Merged spec output path (required) |
| `--format` | `json` or `yaml` (default: `json`) |

## Configuration

CLIaS reads from `clias.toml` in the current directory (or specify with `--config`).

```toml
output_dir = "./clias_output"

[llm]
model = "gpt-4o"                # Primary text model
vision_model = "gpt-4o"         # Multimodal model (for screenshots)
temperature = 0.2               # Low = consistent; high = creative
max_tokens = 4096

[observer]
screenshot_interval = 2.0       # Seconds between captures
change_threshold = 0.05         # Pixel-change threshold for dedup
```

**Using Anthropic Claude:**

```toml
[llm]
model = "anthropic/claude-sonnet-4-20250514"
vision_model = "anthropic/claude-sonnet-4-20250514"
```

**Using local Ollama:**

```toml
[llm]
model = "ollama/llama3"
vision_model = "ollama/llava"
```

## ToolSpec Format

The ToolSpec is the portable intermediate representation at the heart of CLIaS. It's a JSON/YAML file you can inspect, edit by hand, and version-control.

```json
{
  "name": "git",
  "description": "Distributed version control system",
  "version": "1.0",
  "commands": [
    {
      "canonical": "git log --oneline",
      "description": "Show compact commit history",
      "args": [],
      "flags": [
        {"flag": "--oneline", "description": "One line per commit"}
      ],
      "examples": ["git log --oneline -10"]
    }
  ],
  "capabilities": [
    {
      "name": "history",
      "description": "View commit history",
      "related_commands": ["git log --oneline"]
    }
  ],
  "workflows": [],
  "interaction_methods": []
}
```

## Project Structure

```
CLIaS/
├── clias/
│   ├── cli.py                 # Main Click CLI (observe, analyze, generate, skill, ask, merge)
│   ├── config.py              # TOML config loading
│   ├── prompting.py           # Interactive credential prompting
│   ├── observer/
│   │   ├── session.py         # Session manager & manifest
│   │   ├── shell.py           # Shell event recording (PTY + command mode)
│   │   └── screen.py          # Screenshot capture with change detection
│   ├── analyzer/
│   │   ├── shell.py           # LLM-based command classification
│   │   ├── vision.py          # Multimodal screenshot analysis
│   │   └── merger.py          # UI ↔ Shell cross-referencing
│   ├── specgen/
│   │   ├── schema.py          # Pydantic models (ToolSpec, CommandSpec, etc.)
│   │   ├── builder.py         # Spec generation from patterns
│   │   ├── api_parser.py      # Pure-Python curl/httpie argument parser
│   │   └── env_scanner.py     # API key environment variable detection
│   ├── cligen/
│   │   ├── scaffold.py        # Click CLI code generator
│   │   ├── translator.py      # NL → command translation
│   │   └── executor.py        # Safe command execution with confirmation
│   ├── skillgen/
│   │   └── generator.py       # Claude Code skill directory generator
│   └── llm/
│       ├── client.py          # LiteLLM wrapper (provider-agnostic)
│       └── prompts.py         # Prompt templates for each pipeline stage
├── skills/                    # Generated skill directories
├── tests/
│   ├── test_observer/         # Shell recording tests
│   ├── test_analyzer/         # Classification tests (mocked LLM)
│   ├── test_specgen/          # Schema roundtrip & merge tests
│   ├── test_cligen/           # Scaffold & translator tests
│   ├── test_api_parser.py     # curl/httpie parsing tests
│   ├── test_env_scanner.py    # Env var scanning tests
│   ├── test_skillgen.py       # Skill generation tests
│   ├── test_prompting.py      # Credential prompting tests
│   ├── test_e2e_git.py        # Full pipeline E2E (mock LLM)
│   └── test_real_e2e.py       # E2E with live LLM API calls
├── clias.toml                 # Default configuration
├── pyproject.toml             # Project metadata & dependencies
└── PLAN.md                    # Architecture & roadmap
```

## Running Tests

```bash
# All tests (LLM calls are mocked)
pytest tests/ -v

# With live LLM calls (requires API key)
ANTHROPIC_API_KEY=sk-ant-... pytest tests/ -v -s

# Specific test suite
pytest tests/test_e2e_git.py -v
pytest tests/test_specgen/ -v
```

## End-to-End Example: Git

Here's the full pipeline applied to git — from observation to natural language CLI:

```bash
# 1. Record common git operations
clias observe \
  -C "git status" \
  -C "git log --oneline -5" \
  -C "git branch -a" \
  -C "git remote -v" \
  -o ./git_session

# 2. Analyze — the LLM classifies each command
clias analyze ./git_session/session_* -o git_spec.json
# → "Loaded 4 shell events."
# → "4 patterns identified."
# → "Spec saved: git_spec.json"

# 3. Generate a standalone CLI
clias generate git_spec.json -o git_cli.py
# → "CLI generated: git_cli.py"

# 4. Now use natural language
clias ask git_spec.json "show me all branches including remote ones"
# → Proposed: git branch -a
# → Execute? [y/N]

clias ask git_spec.json "what changed in the last 3 commits" --execute
# → git log --oneline -3
# → (executes immediately)
```

## Requirements

- Python 3.11+
- An LLM API key (OpenAI, Anthropic, or local Ollama)
- For screenshot capture: a display server (X11/Wayland) + `mss` + `Pillow`

## License

MIT
