# CLIaS — CLI as a Service: Software Analysis & CLI Generator

## Vision

Turn any observed software into an AI-powered command-line assistant on demand.
The system watches how software is used (GUI interactions + terminal commands),
distills that knowledge into a structured specification, then generates a custom
CLI where users describe what they want in natural language and an LLM translates
it into the correct shell commands.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      CLIaS Pipeline                         │
│                                                             │
│  ┌──────────┐   ┌───────────┐   ┌──────────┐   ┌────────┐ │
│  │ Observer  │──▶│ Analyzer  │──▶│ SpecGen  │──▶│CLIGen  │ │
│  │  Layer    │   │  Engine   │   │          │   │        │ │
│  └──────────┘   └───────────┘   └──────────┘   └────────┘ │
│       │                                             │      │
│       ▼                                             ▼      │
│  Screen + Shell                               Generated    │
│  recordings                                   CLI + LLM    │
│                                               interface    │
└─────────────────────────────────────────────────────────────┘
```

### Four core subsystems

| # | Subsystem              | Responsibility                                      |
|---|------------------------|-----------------------------------------------------|
| 1 | **Observer Layer**     | Record GUI screenshots/video and shell sessions     |
| 2 | **Analyzer Engine**    | Extract actions, patterns, and semantics from traces |
| 3 | **Spec Generator**     | Produce a structured tool specification (JSON/YAML) |
| 4 | **CLI Generator**      | Emit a working CLI that uses an LLM to map NL→cmds  |

---

## Technology Choices

| Concern            | Choice         | Rationale                                              |
|--------------------|----------------|--------------------------------------------------------|
| Language           | Python 3.11+   | Rich ecosystem for screen capture, LLM APIs, CLI libs  |
| Package manager    | uv / pip       | Fast, modern Python packaging                          |
| CLI framework      | Click + Rich   | Composable commands, beautiful terminal output         |
| LLM integration    | LiteLLM        | Provider-agnostic (OpenAI, Anthropic, local models)    |
| Screen capture     | PyAutoGUI + mss| Cross-platform screenshots and region capture          |
| OCR / vision       | GPT-4o / Claude vision | Multimodal LLM for understanding screenshots   |
| Shell recording    | script / asciinema | Standard session recorders                         |
| Structured output  | Pydantic       | Validated spec schemas                                 |
| Testing            | pytest         | Standard, well-supported                               |
| Config             | TOML           | Human-readable, standard for Python projects           |

---

## Detailed Component Design

### 1. Observer Layer (`clias/observer/`)

Captures raw usage data from two channels:

#### 1a. Screen Observer (`screen.py`)
- Periodic screenshot capture at configurable intervals (default: 2s)
- Region-of-interest selection (full screen or specific window)
- Change detection — only save frames that differ significantly from the previous
- Output: timestamped PNG sequence stored in a session directory

#### 1b. Shell Observer (`shell.py`)
- Wraps the user's shell session (via `script` on Linux/macOS, `conpty` on Windows)
- Captures every command entered and its full stdout/stderr output
- Parses the stream into structured `ShellEvent` records:
  ```python
  class ShellEvent:
      timestamp: datetime
      command: str
      exit_code: int
      stdout: str
      stderr: str
      cwd: str
  ```
- Output: JSONL file of `ShellEvent` records

#### 1c. Session Manager (`session.py`)
- Coordinates screen + shell observers into a unified recording session
- Assigns a session ID, manages start/stop lifecycle
- Produces a `SessionManifest` linking screenshots ↔ shell events by timestamp

### 2. Analyzer Engine (`clias/analyzer/`)

Processes raw session data into semantic understanding.

#### 2a. Vision Analyzer (`vision.py`)
- Sends screenshot sequences to a multimodal LLM with a structured prompt:
  *"Describe the UI state, what application is shown, and what action the user
   appears to be performing."*
- Deduplicates and merges consecutive frames with identical descriptions
- Output: ordered list of `UIAction` records

#### 2b. Shell Analyzer (`shell.py`)
- Groups shell events by intent (e.g., "build project", "run tests", "deploy")
- Identifies the tool being used (git, docker, npm, kubectl, etc.)
- Extracts argument patterns, flags, and common option combinations
- Maps commands to higher-level operations via LLM classification
- Output: list of `ShellPattern` records with semantic labels

#### 2c. Cross-Reference Merger (`merger.py`)
- Aligns `UIAction` and `ShellPattern` records on the timeline
- Identifies correlations: "user clicked Deploy button → ran `kubectl apply`"
- Produces a unified `ToolBehavior` model that captures:
  - What the tool does (capabilities)
  - How it's invoked (command patterns)
  - What the GUI equivalents are (if any)
  - Common workflows (ordered sequences of operations)

### 3. Spec Generator (`clias/specgen/`)

Transforms `ToolBehavior` into a formal, reusable specification.

#### 3a. Spec Schema (`schema.py`)
```python
class ToolSpec(BaseModel):
    name: str
    description: str
    version: str
    capabilities: list[Capability]
    commands: list[CommandSpec]
    workflows: list[Workflow]
    examples: list[Example]

class Capability(BaseModel):
    name: str                   # e.g. "container-management"
    description: str
    related_commands: list[str]

class CommandSpec(BaseModel):
    canonical: str              # e.g. "docker run"
    description: str
    arguments: list[ArgSpec]
    flags: list[FlagSpec]
    examples: list[str]
    gui_equivalent: str | None

class Workflow(BaseModel):
    name: str                   # e.g. "deploy-to-staging"
    description: str
    steps: list[WorkflowStep]

class WorkflowStep(BaseModel):
    description: str
    command_ref: str            # references CommandSpec.canonical
    typical_args: dict[str, str]
```

#### 3b. Spec Builder (`builder.py`)
- Takes `ToolBehavior` from the analyzer
- Uses an LLM to fill in gaps (descriptions, arg docs, missing flags)
- Validates output against the Pydantic schema
- Supports incremental refinement — re-observe and merge new data into existing spec
- Output: `tool_spec.json` / `tool_spec.yaml`

### 4. CLI Generator (`clias/cligen/`)

Produces a usable CLI from a `ToolSpec`.

#### 4a. CLI Scaffold (`scaffold.py`)
- Generates a Click-based CLI application from the spec
- Each `Capability` becomes a command group
- Each `CommandSpec` becomes a subcommand with proper arguments/flags
- Adds a top-level `ask` command for natural-language interaction

#### 4b. NL→Command Translator (`translator.py`)
- The core LLM bridge: takes a natural-language request + the ToolSpec context
  and returns executable shell command(s)
- Prompt structure:
  ```
  You are a CLI assistant for {tool.name}.
  Here is what this tool can do: {tool.capabilities}
  Here are the available commands: {tool.commands}

  The user wants: "{user_input}"

  Return the exact shell command(s) to accomplish this.
  ```
- Safety layer: commands are shown to the user for confirmation before execution
- Supports `--dry-run` (show command only) and `--execute` (run immediately)

#### 4c. Runtime Executor (`executor.py`)
- Runs approved commands in a subprocess
- Streams stdout/stderr to the terminal in real time
- Captures results for follow-up questions ("that failed — what went wrong?")

---

## Project Structure

```
CLIaS/
├── pyproject.toml
├── README.md
├── clias/
│   ├── __init__.py
│   ├── cli.py                  # Main entry point (Click app)
│   ├── config.py               # Global config loading (TOML)
│   ├── observer/
│   │   ├── __init__.py
│   │   ├── screen.py           # Screenshot capture
│   │   ├── shell.py            # Shell session recording
│   │   └── session.py          # Unified session manager
│   ├── analyzer/
│   │   ├── __init__.py
│   │   ├── vision.py           # Screenshot → UIAction
│   │   ├── shell.py            # ShellEvent → ShellPattern
│   │   └── merger.py           # Cross-reference alignment
│   ├── specgen/
│   │   ├── __init__.py
│   │   ├── schema.py           # Pydantic ToolSpec models
│   │   └── builder.py          # ToolBehavior → ToolSpec
│   ├── cligen/
│   │   ├── __init__.py
│   │   ├── scaffold.py         # ToolSpec → Click CLI
│   │   ├── translator.py       # NL → shell commands (LLM)
│   │   └── executor.py         # Safe command execution
│   └── llm/
│       ├── __init__.py
│       ├── client.py           # LiteLLM wrapper
│       └── prompts.py          # Prompt templates
├── tests/
│   ├── test_observer/
│   ├── test_analyzer/
│   ├── test_specgen/
│   └── test_cligen/
├── examples/
│   └── specs/                  # Example generated specs
└── clias.toml                  # Default config
```

---

## Implementation Phases

### Phase 1 — Foundation & Shell Observer
- [ ] Project scaffolding (pyproject.toml, directory structure, configs)
- [ ] LLM client wrapper with LiteLLM
- [ ] Shell observer: record and parse terminal sessions into ShellEvents
- [ ] Shell analyzer: classify commands into ShellPatterns via LLM
- [ ] Pydantic ToolSpec schema
- [ ] Basic spec builder (shell-only, no vision yet)
- [ ] Unit tests for observer + analyzer

### Phase 2 — CLI Generation & NL Interface
- [ ] CLI scaffold generator from ToolSpec
- [ ] NL→Command translator with confirmation flow
- [ ] Runtime executor with streaming output
- [ ] `clias ask "..."` command for natural-language queries
- [ ] `clias observe` command to start a recording session
- [ ] `clias generate` command to build a CLI from a spec
- [ ] Integration tests for the full observe→generate pipeline

### Phase 3 — Screen Observer & Vision
- [ ] Screenshot capture with change detection
- [ ] Vision analyzer: screenshots → UIAction via multimodal LLM
- [ ] Cross-reference merger: align UI actions with shell events
- [ ] Enrich spec with GUI equivalents
- [ ] Tests for vision pipeline

### Phase 4 — Polish & Distribution
- [ ] Incremental spec refinement (merge new observations into existing spec)
- [ ] Workflow detection (multi-step operation sequences)
- [ ] Config file support (clias.toml)
- [ ] `--dry-run` and safety guardrails
- [ ] Documentation and examples
- [ ] PyPI packaging

---

## CLI UX (target interface)

```bash
# Record a session (shell + optional screen capture)
$ clias observe --screen --output ./session-docker
  Recording... press Ctrl+C to stop.

# Analyze a recorded session and generate a spec
$ clias analyze ./session-docker -o docker_spec.yaml

# Generate a CLI from a spec
$ clias generate docker_spec.yaml -o ./my-docker-cli

# Use the generated CLI with natural language
$ ./my-docker-cli ask "spin up a postgres container on port 5432"
  Proposed command:
    docker run -d --name postgres -p 5432:5432 -e POSTGRES_PASSWORD=secret postgres:16
  Execute? [y/N]

# Or use the structured subcommands directly
$ ./my-docker-cli container run --image postgres --port 5432:5432
```

---

## Key Design Decisions

1. **LLM-agnostic via LiteLLM** — Users bring their own API key; works with
   OpenAI, Anthropic, local Ollama, etc.

2. **Confirmation before execution** — Generated commands are always shown to
   the user first. No blind execution.

3. **Spec as the intermediate representation** — The JSON/YAML spec is a
   portable, inspectable, editable artifact. Users can hand-tune it.

4. **Incremental learning** — Multiple observation sessions can be merged into
   one spec, progressively improving coverage.

5. **Separation of observation and generation** — The observer produces raw
   data; analysis and generation are separate steps. This lets users re-analyze
   with different LLMs or prompts without re-recording.
