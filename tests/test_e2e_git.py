#!/usr/bin/env python3
"""
End-to-end integration test: Observe a real git session → Analyze → Generate CLI → Ask.

Runs the full CLIaS pipeline against a real git repository using realistic
mock LLM responses. Also includes live-LLM tests (skipped without ANTHROPIC_API_KEY).

Usage:
    python -m pytest tests/test_e2e_git.py -v -s
    ANTHROPIC_API_KEY=sk-... python -m pytest tests/test_e2e_git.py -v -s  # include live tests
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clias.config import LLMConfig
from clias.llm.client import LLMClient
from clias.observer.shell import ShellObserver
from clias.analyzer.shell import ShellAnalyzer
from clias.specgen.builder import SpecBuilder
from clias.specgen.schema import ToolSpec
from clias.cligen.scaffold import CLIScaffold
from clias.cligen.translator import NLTranslator
from clias.cligen.executor import Executor, ExecutionResult


ANTHROPIC_MODEL = "anthropic/claude-sonnet-4-20250514"

requires_live_llm = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live LLM test",
)


# ──────────────────────────────────────────────────────────────────────
# Realistic mock LLM responses (based on what Claude actually returns)
# ──────────────────────────────────────────────────────────────────────

MOCK_CLASSIFY_RESPONSES = {
    "git status": json.dumps({
        "tool": "git",
        "operation": "check-status",
        "description": "Shows the current state of the working tree, listing staged, unstaged, and untracked files",
        "flags_used": [],
        "is_destructive": False,
    }),
    "git log": json.dumps({
        "tool": "git",
        "operation": "view-history",
        "description": "Displays the commit history in a condensed one-line-per-commit format",
        "flags_used": ["--oneline"],
        "is_destructive": False,
    }),
    "git branch": json.dumps({
        "tool": "git",
        "operation": "list-branches",
        "description": "Lists all local and remote branches in the repository",
        "flags_used": ["-a"],
        "is_destructive": False,
    }),
    "git diff": json.dumps({
        "tool": "git",
        "operation": "view-changes",
        "description": "Shows the differences between the current HEAD and the previous commit",
        "flags_used": ["HEAD~1"],
        "is_destructive": False,
    }),
    "git show": json.dumps({
        "tool": "git",
        "operation": "inspect-commit",
        "description": "Displays the files changed in the most recent commit along with diffstat",
        "flags_used": ["--stat"],
        "is_destructive": False,
    }),
    "git add": json.dumps({
        "tool": "git",
        "operation": "stage-changes",
        "description": "Stages all changes in the working directory for the next commit",
        "flags_used": ["."],
        "is_destructive": False,
    }),
}

MOCK_SPEC_RESPONSE = json.dumps({
    "name": "git",
    "description": "Git is a distributed version control system for tracking changes in source code during software development",
    "version": "observed",
    "capabilities": [
        {
            "name": "version-control",
            "description": "Track and manage changes to source code files",
            "related_commands": ["git add", "git commit", "git status"],
        },
        {
            "name": "history-inspection",
            "description": "View and navigate commit history and changes",
            "related_commands": ["git log", "git diff", "git show"],
        },
        {
            "name": "branching",
            "description": "Create and manage parallel lines of development",
            "related_commands": ["git branch", "git checkout", "git merge"],
        },
    ],
    "commands": [
        {
            "canonical": "git status",
            "description": "Show the working tree status — staged, unstaged, and untracked files",
            "arguments": [],
            "flags": [
                {"flag": "-s", "description": "Short format output", "takes_value": False},
                {"flag": "--porcelain", "description": "Machine-readable output", "takes_value": False},
            ],
            "examples": ["git status", "git status -s"],
            "gui_equivalent": None,
        },
        {
            "canonical": "git log",
            "description": "Show commit history",
            "arguments": [],
            "flags": [
                {"flag": "--oneline", "description": "Condensed one-line format", "takes_value": False},
                {"flag": "-n", "description": "Limit number of commits", "takes_value": True},
                {"flag": "--graph", "description": "Draw ASCII graph of branch structure", "takes_value": False},
            ],
            "examples": ["git log --oneline", "git log -n 5", "git log --graph --oneline"],
            "gui_equivalent": None,
        },
        {
            "canonical": "git branch",
            "description": "List, create, or delete branches",
            "arguments": [{"name": "branch_name", "description": "Name of branch to create", "required": False}],
            "flags": [
                {"flag": "-a", "description": "List all branches (local + remote)", "takes_value": False},
                {"flag": "-d", "description": "Delete a branch", "takes_value": False},
            ],
            "examples": ["git branch", "git branch -a", "git branch feature/new"],
            "gui_equivalent": None,
        },
        {
            "canonical": "git diff",
            "description": "Show changes between commits, working tree, and staging area",
            "arguments": [{"name": "commit", "description": "Commit reference to diff against", "required": False}],
            "flags": [
                {"flag": "--stat", "description": "Show diffstat summary", "takes_value": False},
                {"flag": "--cached", "description": "Show staged changes", "takes_value": False},
            ],
            "examples": ["git diff", "git diff HEAD~1", "git diff --cached"],
            "gui_equivalent": None,
        },
        {
            "canonical": "git show",
            "description": "Show information about a commit",
            "arguments": [{"name": "commit", "description": "Commit to show", "required": False}],
            "flags": [
                {"flag": "--stat", "description": "Show diffstat only", "takes_value": False},
            ],
            "examples": ["git show", "git show --stat HEAD"],
            "gui_equivalent": None,
        },
        {
            "canonical": "git add",
            "description": "Stage file contents for the next commit",
            "arguments": [{"name": "path", "description": "Files or directories to stage", "required": True}],
            "flags": [
                {"flag": "-p", "description": "Interactively choose hunks to stage", "takes_value": False},
            ],
            "examples": ["git add .", "git add main.py", "git add -p"],
            "gui_equivalent": None,
        },
    ],
    "workflows": [
        {
            "name": "basic-commit-flow",
            "description": "Stage changes and commit them",
            "steps": [
                {"description": "Check current status", "command_ref": "git status", "typical_args": {}},
                {"description": "Stage all changes", "command_ref": "git add", "typical_args": {"path": "."}},
                {"description": "Review staged changes", "command_ref": "git diff", "typical_args": {"commit": "--cached"}},
            ],
        }
    ],
    "examples": [
        {"description": "Check status", "command": "git status"},
        {"description": "View recent commits", "command": "git log --oneline -10"},
        {"description": "Stage and review", "command": "git add . && git diff --cached"},
    ],
})

MOCK_INTERACTION_RESPONSE = json.dumps([
    {
        "method": "cli",
        "description": "Primary interaction through the git command-line interface",
        "base_url": None,
        "auth_type": "none",
        "auth_env_var": None,
        "notes": "Git uses SSH keys or HTTPS credentials for remote operations",
    },
    {
        "method": "rest_api",
        "description": "GitHub/GitLab REST APIs for remote repository management",
        "base_url": "https://api.github.com",
        "auth_type": "token",
        "auth_env_var": "GITHUB_TOKEN",
        "notes": "Used for pull requests, issues, and CI/CD integration",
    },
])

MOCK_NL_RESPONSES = {
    "show me the commit history": "git log --oneline",
    "what files have changed": "git status",
    "create a new branch called bugfix": "git branch bugfix",
    "stage all modified files": "git add .",
    "show the last 3 commits": "git log --oneline -3",
    "undo the last commit": "git reset --soft HEAD~1",
}


def _make_mock_llm() -> MagicMock:
    """Create a mock LLM that returns realistic responses based on input content."""
    llm = MagicMock(spec=LLMClient)

    def mock_ask(prompt: str, *, system: str | None = None) -> str:
        prompt_lower = prompt.lower()

        # NL translation (check FIRST — these prompts contain "user wants:")
        if "the user wants:" in prompt_lower or "user wants:" in prompt_lower:
            for key, response in MOCK_NL_RESPONSES.items():
                if key in prompt_lower:
                    return response
            return "git status"

        # Spec building (check before classify — these prompts contain the spec schema)
        if "toolspec" in prompt_lower or "produce a complete" in prompt_lower or "follow this structure" in prompt_lower:
            return MOCK_SPEC_RESPONSE

        # Interaction detection
        if "interaction method" in prompt_lower or "beyond basic cli" in prompt_lower:
            return MOCK_INTERACTION_RESPONSE

        # Shell classification (most prompts contain "command:" with a git command)
        for key, response in MOCK_CLASSIFY_RESPONSES.items():
            if key in prompt_lower:
                return response

        # Fallback
        return json.dumps({"tool": "unknown", "operation": "unknown", "description": "unknown", "flags_used": [], "is_destructive": False})

    llm.ask.side_effect = mock_ask
    return llm


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_git_repo(tmp_path: Path) -> Path:
    """Create a throwaway git repo with real history."""
    repo = tmp_path / "sample_project"
    repo.mkdir()

    env = {**os.environ, "GIT_COMMITTER_NAME": "CLIaS Test", "GIT_COMMITTER_EMAIL": "test@clias.dev"}

    def run(cmd: str) -> None:
        subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, check=True, env=env)

    run("git init -b main")
    run("git config user.email 'test@clias.dev'")
    run("git config user.name 'CLIaS Test'")
    run("git config commit.gpgsign false")

    # Create initial files
    (repo / "main.py").write_text("print('hello world')\n")
    (repo / "README.md").write_text("# Sample Project\n\nA demo project.\n")
    run("git add .")
    run("git commit -m 'Initial commit'")

    # Add a feature
    (repo / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "main.py").write_text("from utils import add\nprint(add(1, 2))\n")
    run("git add .")
    run("git commit -m 'Add utils module with add function'")

    # Create a branch
    run("git checkout -b feature/multiply")
    (repo / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n"
    )
    run("git add .")
    run("git commit -m 'Add multiply function'")
    run("git checkout main")

    return repo


@pytest.fixture
def mock_llm() -> MagicMock:
    return _make_mock_llm()


# ──────────────────────────────────────────────────────────────────────
# Phase 1: Observe (real git commands, no LLM needed)
# ──────────────────────────────────────────────────────────────────────

class TestPhase1Observe:
    """Record real git commands and verify ShellEvents are captured."""

    def test_observe_git_commands(self, sample_git_repo: Path, tmp_path: Path) -> None:
        observer = ShellObserver(tmp_path / "session")
        commands = [
            f"cd {sample_git_repo} && git status",
            f"cd {sample_git_repo} && git log --oneline",
            f"cd {sample_git_repo} && git branch -a",
            f"cd {sample_git_repo} && git diff HEAD~1",
            f"cd {sample_git_repo} && git show --stat HEAD",
        ]

        for cmd in commands:
            event = observer.record_command(cmd)
            assert event.exit_code == 0, f"Command failed: {cmd}\nstderr: {event.stderr}"

        events = observer.get_events()
        assert len(events) == 5

        # Verify persistence
        loaded = ShellObserver.load_events(observer.events_file)
        assert len(loaded) == 5

        # Spot-check real git output
        assert "main" in events[0].stdout.lower() or "branch" in events[0].stdout.lower()
        assert "Initial commit" in events[1].stdout

        print(f"\n  Phase 1 — Observed {len(events)} git commands:")
        for e in events:
            stdout_preview = e.stdout.strip().split("\n")[0][:60]
            print(f"    [{e.exit_code}] {e.command.split('&&')[-1].strip()}")
            print(f"         → {stdout_preview}")

    def test_observe_via_cli_command(self, sample_git_repo: Path, tmp_path: Path) -> None:
        """Test the `clias observe -C` CLI interface."""
        session_dir = tmp_path / "cli_session"
        result = subprocess.run(
            [
                "clias", "observe",
                "--output", str(session_dir),
                "-C", f"cd {sample_git_repo} && git status",
                "-C", f"cd {sample_git_repo} && git log --oneline",
                "-C", f"cd {sample_git_repo} && git branch -a",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"clias observe failed:\n{result.stderr}"
        assert "Session saved" in result.stdout

        sessions = list(session_dir.glob("session_*"))
        assert len(sessions) == 1

        events_file = sessions[0] / "shell_events.jsonl"
        assert events_file.exists()

        events = ShellObserver.load_events(events_file)
        assert len(events) == 3

        print(f"\n  Phase 1b — CLI observe captured {len(events)} events")
        print(f"    Session dir: {sessions[0]}")


# ──────────────────────────────────────────────────────────────────────
# Phase 2: Analyze (mock LLM with realistic responses)
# ──────────────────────────────────────────────────────────────────────

class TestPhase2Analyze:
    """Classify observed shell events into semantic patterns."""

    def test_analyze_git_events(self, sample_git_repo: Path, tmp_path: Path, mock_llm: MagicMock) -> None:
        # Observe real git commands
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {sample_git_repo} && git status",
            f"cd {sample_git_repo} && git log --oneline",
            f"cd {sample_git_repo} && git branch -a",
            f"cd {sample_git_repo} && git diff HEAD~1",
        ]:
            observer.record_command(cmd)
        events = observer.get_events()
        assert len(events) == 4

        # Analyze with mock LLM
        analyzer = ShellAnalyzer(mock_llm)
        patterns = analyzer.classify_batch(events)

        assert len(patterns) == 4
        for p in patterns:
            assert p.tool == "git"
            assert p.description
            assert p.operation

        # Verify grouping
        groups = analyzer.group_by_tool(patterns)
        assert "git" in groups
        assert len(groups["git"]) == 4

        print(f"\n  Phase 2 — Analyzed {len(patterns)} events:")
        for p in patterns:
            print(f"    [{p.tool}] {p.operation}: {p.description[:70]}")
            print(f"      flags={p.flags_used}, destructive={p.is_destructive}")


# ──────────────────────────────────────────────────────────────────────
# Phase 3: Build Spec
# ──────────────────────────────────────────────────────────────────────

class TestPhase3SpecGen:
    """Build a ToolSpec from analyzed patterns."""

    def test_build_spec_from_patterns(self, sample_git_repo: Path, tmp_path: Path, mock_llm: MagicMock) -> None:
        # Observe
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {sample_git_repo} && git status",
            f"cd {sample_git_repo} && git log --oneline",
            f"cd {sample_git_repo} && git branch -a",
            f"cd {sample_git_repo} && git diff HEAD~1",
            f"cd {sample_git_repo} && git show --stat HEAD",
            f"cd {sample_git_repo} && git add .",
        ]:
            observer.record_command(cmd)

        # Analyze
        analyzer = ShellAnalyzer(mock_llm)
        patterns = analyzer.classify_batch(observer.get_events())

        # Build spec
        builder = SpecBuilder(mock_llm)
        spec = builder.build_from_patterns(patterns)

        # Validate the spec
        assert spec.name == "git"
        assert "version control" in spec.description.lower()
        assert len(spec.commands) >= 6
        assert len(spec.capabilities) >= 3
        assert len(spec.workflows) >= 1
        assert len(spec.interaction_methods) >= 1

        # Verify specific commands exist
        cmd_names = {c.canonical for c in spec.commands}
        assert "git status" in cmd_names
        assert "git log" in cmd_names
        assert "git add" in cmd_names
        assert "git branch" in cmd_names

        # Verify interaction methods
        methods = {m.method for m in spec.interaction_methods}
        assert "cli" in methods
        assert "rest_api" in methods
        api_method = next(m for m in spec.interaction_methods if m.method == "rest_api")
        assert api_method.auth_env_var == "GITHUB_TOKEN"

        # Save and reload
        spec_json = tmp_path / "git_spec.json"
        spec_yaml = tmp_path / "git_spec.yaml"
        spec.save_json(spec_json)
        spec.save_yaml(spec_yaml)

        reloaded_json = ToolSpec.load(spec_json)
        reloaded_yaml = ToolSpec.load(spec_yaml)
        assert reloaded_json.name == "git"
        assert reloaded_yaml.name == "git"
        assert len(reloaded_json.commands) == len(spec.commands)

        print(f"\n  Phase 3 — Built ToolSpec for '{spec.name}':")
        print(f"    Description: {spec.description[:80]}")
        print(f"    Commands:     {len(spec.commands)}")
        print(f"    Capabilities: {len(spec.capabilities)}")
        print(f"    Workflows:    {len(spec.workflows)}")
        print(f"    Interactions: {', '.join(methods)}")
        print(f"    Saved to: {spec_json}")
        for cmd in spec.commands:
            flags = " ".join(f.flag for f in cmd.flags)
            print(f"      {cmd.canonical} [{flags}] — {cmd.description[:50]}")


# ──────────────────────────────────────────────────────────────────────
# Phase 4: Generate CLI
# ──────────────────────────────────────────────────────────────────────

class TestPhase4GenerateCLI:
    """Generate a working CLI from the ToolSpec."""

    def test_generate_and_validate_cli(self, sample_git_repo: Path, tmp_path: Path, mock_llm: MagicMock) -> None:
        # Full pipeline up to spec
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {sample_git_repo} && git status",
            f"cd {sample_git_repo} && git log --oneline",
            f"cd {sample_git_repo} && git branch -a",
            f"cd {sample_git_repo} && git diff HEAD~1",
            f"cd {sample_git_repo} && git add .",
        ]:
            observer.record_command(cmd)

        analyzer = ShellAnalyzer(mock_llm)
        patterns = analyzer.classify_batch(observer.get_events())
        builder = SpecBuilder(mock_llm)
        spec = builder.build_from_patterns(patterns)

        # Generate CLI
        cli_path = tmp_path / "git_cli.py"
        scaffold = CLIScaffold(spec)
        scaffold.generate(cli_path)

        assert cli_path.exists()
        content = cli_path.read_text()

        # Verify structure
        assert "#!/usr/bin/env python3" in content
        assert "TOOL_SPEC" in content
        assert "def ask(" in content
        assert "def cli():" in content
        assert '"name": "git"' in content
        assert "click" in content

        # Verify it's valid Python that can be parsed
        result = subprocess.run(
            ["python", "-c", f"import ast; ast.parse(open('{cli_path}').read()); print('VALID')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Generated CLI has syntax errors:\n{result.stderr}"
        assert "VALID" in result.stdout

        # Verify it's executable
        assert os.access(cli_path, os.X_OK)

        print(f"\n  Phase 4 — Generated CLI:")
        print(f"    Path: {cli_path}")
        print(f"    Size: {cli_path.stat().st_size:,} bytes")
        print(f"    Lines: {len(content.splitlines())}")
        print(f"    Valid Python: yes")
        print(f"    Executable: yes")
        print(f"    Contains ask command: yes")
        print(f"    Contains TOOL_SPEC: yes")


# ──────────────────────────────────────────────────────────────────────
# Phase 5: NL → Command Translation
# ──────────────────────────────────────────────────────────────────────

class TestPhase5NLTranslation:
    """Translate natural language requests to git commands."""

    def test_nl_to_commands(self, mock_llm: MagicMock) -> None:
        # Build a spec directly from mock
        spec = ToolSpec.model_validate(json.loads(MOCK_SPEC_RESPONSE))
        spec.interaction_methods = [
            __import__("clias.specgen.schema", fromlist=["InteractionMethod"]).InteractionMethod(
                method="rest_api",
                auth_type="token",
                auth_env_var="GITHUB_TOKEN",
                description="GitHub API",
            )
        ]

        translator = NLTranslator(mock_llm, spec)

        test_cases = [
            ("show me the commit history", "git log"),
            ("what files have changed", "git status"),
            ("create a new branch called bugfix", "git branch"),
            ("stage all modified files", "git add"),
        ]

        print(f"\n  Phase 5 — NL → Command translations:")
        for nl_input, expected in test_cases:
            commands = translator.translate(nl_input)
            assert len(commands) > 0, f"No commands for: '{nl_input}'"
            joined = " ".join(commands).lower()
            assert expected in joined, f"Expected '{expected}' in {commands}"
            print(f'    "{nl_input}"')
            for c in commands:
                print(f"      → {c}")

        # Verify auth context was included in the prompt
        for call_args in mock_llm.ask.call_args_list:
            prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
            if "user wants" in prompt.lower():
                assert "GITHUB_TOKEN" in prompt, "Auth context should be in translation prompt"
                break


# ──────────────────────────────────────────────────────────────────────
# Phase 6: Executor (safe command execution)
# ──────────────────────────────────────────────────────────────────────

class TestPhase6Executor:
    """Verify safe command execution with dry-run and real execution."""

    def test_dry_run(self, sample_git_repo: Path) -> None:
        executor = Executor(dry_run=True)
        results = executor.run([f"cd {sample_git_repo} && git status"])
        assert len(results) == 1
        assert results[0].success
        assert results[0].return_code == 0

        print(f"\n  Phase 6a — Dry run: command not executed (correct)")

    def test_auto_confirm_execution(self, sample_git_repo: Path) -> None:
        executor = Executor(auto_confirm=True)
        results = executor.run([f"cd {sample_git_repo} && git log --oneline -3"])
        assert len(results) == 1
        assert results[0].success
        assert results[0].return_code == 0

        print(f"\n  Phase 6b — Auto-confirm: command executed successfully")

    def test_stops_on_failure(self) -> None:
        executor = Executor(auto_confirm=True)
        results = executor.run(["true", "false", "echo should-not-run"])
        assert len(results) == 2
        assert results[0].success
        assert not results[1].success

        print(f"\n  Phase 6c — Stops on failure: correctly halted after 'false'")


# ──────────────────────────────────────────────────────────────────────
# Full Pipeline (end-to-end, all phases)
# ──────────────────────────────────────────────────────────────────────

class TestFullPipeline:
    """Run the entire observe → analyze → generate → translate pipeline."""

    def test_full_pipeline(self, sample_git_repo: Path, tmp_path: Path, mock_llm: MagicMock) -> None:
        print(f"\n{'='*60}")
        print(f"  FULL E2E PIPELINE: git observation → AI CLI")
        print(f"{'='*60}")

        # ── Step 1: Observe ──
        observer = ShellObserver(tmp_path / "session")
        git_commands = [
            f"cd {sample_git_repo} && git status",
            f"cd {sample_git_repo} && git log --oneline",
            f"cd {sample_git_repo} && git branch -a",
            f"cd {sample_git_repo} && git diff HEAD~1",
            f"cd {sample_git_repo} && git show --stat HEAD",
            f"cd {sample_git_repo} && git add .",
        ]
        for cmd in git_commands:
            observer.record_command(cmd)
        events = observer.get_events()
        print(f"\n  [1/5] OBSERVE: Recorded {len(events)} real git commands")

        # ── Step 2: Analyze ──
        analyzer = ShellAnalyzer(mock_llm)
        patterns = analyzer.classify_batch(events)
        groups = analyzer.group_by_tool(patterns)
        print(f"  [2/5] ANALYZE: Classified into {len(patterns)} patterns ({', '.join(groups.keys())})")

        # ── Step 3: Generate Spec ──
        builder = SpecBuilder(mock_llm)
        spec = builder.build_from_patterns(patterns)
        spec_path = tmp_path / "git_spec.json"
        spec.save_json(spec_path)
        print(f"  [3/5] SPEC:    Generated '{spec.name}' — {len(spec.commands)} commands, {len(spec.capabilities)} capabilities")

        # ── Step 4: Generate CLI ──
        cli_path = tmp_path / "git_cli.py"
        scaffold = CLIScaffold(spec)
        scaffold.generate(cli_path)
        # Validate
        result = subprocess.run(
            ["python", "-c", f"import ast; ast.parse(open('{cli_path}').read())"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        print(f"  [4/5] CLI:     Generated {cli_path.stat().st_size:,}-byte CLI (valid Python)")

        # ── Step 5: Translate NL → Commands ──
        translator = NLTranslator(mock_llm, spec)
        nl_tests = [
            ("show me the commit history", "git log"),
            ("what files have changed", "git status"),
            ("stage all modified files", "git add"),
        ]
        print(f"  [5/5] ASK:     NL → Command translations:")
        for nl_input, expected in nl_tests:
            commands = translator.translate(nl_input)
            assert any(expected in c.lower() for c in commands)
            print(f'           "{nl_input}" → {commands[0]}')

        print(f"\n{'='*60}")
        print(f"  PIPELINE COMPLETE")
        print(f"  Spec:  {spec_path}")
        print(f"  CLI:   {cli_path}")
        print(f"  Usage: python {cli_path.name} ask 'your request'")
        print(f"{'='*60}")

        # Final assertions
        assert len(events) == 6
        assert len(patterns) == 6
        assert spec.name == "git"
        assert len(spec.commands) >= 6
        assert cli_path.exists()


# ──────────────────────────────────────────────────────────────────────
# Live LLM tests (only run when ANTHROPIC_API_KEY is set)
# ──────────────────────────────────────────────────────────────────────

@requires_live_llm
class TestLiveLLM:
    """Tests that call the real Anthropic API — skipped without ANTHROPIC_API_KEY."""

    def test_live_classify(self, sample_git_repo: Path, tmp_path: Path) -> None:
        observer = ShellObserver(tmp_path / "session")
        observer.record_command(f"cd {sample_git_repo} && git status")
        observer.record_command(f"cd {sample_git_repo} && git log --oneline")

        llm = LLMClient(LLMConfig(model=ANTHROPIC_MODEL, temperature=0.1))
        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())

        assert len(patterns) == 2
        for p in patterns:
            assert p.tool == "git"
        print(f"\n  Live LLM: Classified {len(patterns)} events with real Claude API")

    def test_live_full_pipeline(self, sample_git_repo: Path, tmp_path: Path) -> None:
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {sample_git_repo} && git status",
            f"cd {sample_git_repo} && git log --oneline",
            f"cd {sample_git_repo} && git branch -a",
        ]:
            observer.record_command(cmd)

        llm = LLMClient(LLMConfig(model=ANTHROPIC_MODEL, temperature=0.1))
        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())

        builder = SpecBuilder(llm)
        spec = builder.build_from_patterns(patterns)
        assert spec.name
        assert len(spec.commands) > 0

        translator = NLTranslator(llm, spec)
        commands = translator.translate("show me the commit history")
        assert len(commands) > 0
        assert any("git log" in c.lower() for c in commands)

        print(f"\n  Live LLM: Full pipeline → '{spec.name}' with {len(spec.commands)} commands")
        print(f"  NL translate: 'show me the commit history' → {commands[0]}")
