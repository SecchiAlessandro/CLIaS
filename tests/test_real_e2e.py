#!/usr/bin/env python3
"""
Real end-to-end test: Observe git → Analyze with Claude → Generate spec → Build CLI → Ask.

This test makes REAL calls to the Anthropic Claude API (via LiteLLM).
Requires ANTHROPIC_API_KEY to be set.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python -m pytest tests/test_real_e2e.py -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from clias.config import LLMConfig
from clias.llm.client import LLMClient
from clias.observer.shell import ShellObserver
from clias.analyzer.shell import ShellAnalyzer
from clias.specgen.builder import SpecBuilder
from clias.specgen.schema import ToolSpec
from clias.cligen.scaffold import CLIScaffold
from clias.cligen.translator import NLTranslator
from clias.cligen.executor import Executor


# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

ANTHROPIC_MODEL = "anthropic/claude-sonnet-4-20250514"

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping real API test",
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a realistic git repository with branches, tags, and history."""
    repo = tmp_path / "demo_project"
    repo.mkdir()

    env = {
        **os.environ,
        "GIT_COMMITTER_NAME": "CLIaS Demo",
        "GIT_COMMITTER_EMAIL": "demo@clias.dev",
    }

    def run(cmd: str) -> None:
        subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, check=True, env=env)

    # Init repo
    run("git init -b main")
    run("git config user.email 'demo@clias.dev'")
    run("git config user.name 'CLIaS Demo'")
    run("git config commit.gpgsign false")

    # Commit 1: initial project
    (repo / "app.py").write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        \"\"\"A simple calculator app.\"\"\"

        def add(a: float, b: float) -> float:
            return a + b

        def subtract(a: float, b: float) -> float:
            return a - b

        if __name__ == "__main__":
            print(f"2 + 3 = {add(2, 3)}")
    """))
    (repo / "README.md").write_text("# Calculator\n\nA simple Python calculator.\n")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.env\n")
    run("git add .")
    run("git commit -m 'Initial commit: calculator app with add and subtract'")

    # Commit 2: add tests
    (repo / "test_app.py").write_text(textwrap.dedent("""\
        from app import add, subtract

        def test_add():
            assert add(2, 3) == 5
            assert add(-1, 1) == 0

        def test_subtract():
            assert subtract(5, 3) == 2
            assert subtract(0, 0) == 0
    """))
    run("git add test_app.py")
    run("git commit -m 'Add unit tests for add and subtract'")

    # Commit 3: feature branch with multiply
    run("git checkout -b feature/multiply")
    (repo / "app.py").write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        \"\"\"A simple calculator app.\"\"\"

        def add(a: float, b: float) -> float:
            return a + b

        def subtract(a: float, b: float) -> float:
            return a - b

        def multiply(a: float, b: float) -> float:
            return a * b

        if __name__ == "__main__":
            print(f"2 + 3 = {add(2, 3)}")
            print(f"4 * 5 = {multiply(4, 5)}")
    """))
    (repo / "test_app.py").write_text(textwrap.dedent("""\
        from app import add, subtract, multiply

        def test_add():
            assert add(2, 3) == 5
            assert add(-1, 1) == 0

        def test_subtract():
            assert subtract(5, 3) == 2
            assert subtract(0, 0) == 0

        def test_multiply():
            assert multiply(4, 5) == 20
            assert multiply(0, 100) == 0
    """))
    run("git add .")
    run("git commit -m 'Add multiply function with tests'")
    run("git checkout main")

    # Tag the latest on main
    run("git tag v0.1.0")

    return repo


@pytest.fixture
def llm() -> LLMClient:
    """Create an LLMClient configured for Anthropic Claude."""
    return LLMClient(LLMConfig(model=ANTHROPIC_MODEL, temperature=0.1, max_tokens=4096))


# ──────────────────────────────────────────────────────────────────────
# Real E2E test — full pipeline with live Claude
# ──────────────────────────────────────────────────────────────────────


@requires_api_key
class TestRealPipeline:
    """End-to-end test that calls real Claude API for every stage."""

    def test_phase1_observe_real_git(self, git_repo: Path, tmp_path: Path) -> None:
        """Phase 1: Record real git commands against a real repo."""
        observer = ShellObserver(tmp_path / "session")
        commands = [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline --all",
            f"cd {git_repo} && git branch -a",
            f"cd {git_repo} && git diff HEAD~1",
            f"cd {git_repo} && git show --stat HEAD",
            f"cd {git_repo} && git tag -l",
            f"cd {git_repo} && git log --oneline --graph --all",
        ]

        for cmd in commands:
            event = observer.record_command(cmd)
            assert event.exit_code == 0, f"Failed: {cmd}\n{event.stderr}"

        events = observer.get_events()
        assert len(events) == 7

        # Verify real git output was captured
        status_out = events[0].stdout
        log_out = events[1].stdout
        branch_out = events[2].stdout

        assert "main" in branch_out or "main" in status_out
        assert "Initial commit" in log_out
        assert "multiply" in log_out  # feature branch commit
        assert "v0.1.0" in events[5].stdout  # tag

        # Persist and reload
        loaded = ShellObserver.load_events(observer.events_file)
        assert len(loaded) == len(events)

        print(f"\n{'='*60}")
        print("  PHASE 1: OBSERVE — Real git commands recorded")
        print(f"{'='*60}")
        for e in events:
            cmd_short = e.command.split("&&")[-1].strip()
            out_preview = e.stdout.strip().split("\n")[0][:70]
            print(f"  [{e.exit_code}] {cmd_short}")
            print(f"       → {out_preview}")

    def test_phase2_analyze_with_claude(self, git_repo: Path, tmp_path: Path, llm: LLMClient) -> None:
        """Phase 2: Classify git commands using real Claude API."""
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline --all",
            f"cd {git_repo} && git branch -a",
            f"cd {git_repo} && git diff HEAD~1",
            f"cd {git_repo} && git tag -l",
        ]:
            observer.record_command(cmd)

        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())

        assert len(patterns) == 5
        for p in patterns:
            assert p.tool == "git", f"Expected tool='git', got '{p.tool}' for {p.command}"
            assert p.operation, f"Empty operation for {p.command}"
            assert p.description, f"Empty description for {p.command}"
            assert isinstance(p.is_destructive, bool)

        # All these commands are non-destructive reads
        for p in patterns:
            assert not p.is_destructive, f"'{p.command}' should not be destructive"

        groups = analyzer.group_by_tool(patterns)
        assert "git" in groups
        assert len(groups["git"]) == 5

        print(f"\n{'='*60}")
        print("  PHASE 2: ANALYZE — Claude classified shell events")
        print(f"{'='*60}")
        for p in patterns:
            cmd_short = p.command.split("&&")[-1].strip()
            print(f"  [{p.tool}] {p.operation}")
            print(f"    cmd:  {cmd_short}")
            print(f"    desc: {p.description}")
            print(f"    flags: {p.flags_used}  destructive: {p.is_destructive}")

    def test_phase3_build_spec_with_claude(self, git_repo: Path, tmp_path: Path, llm: LLMClient) -> None:
        """Phase 3: Build a ToolSpec from patterns using real Claude API."""
        # Observe
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline --all",
            f"cd {git_repo} && git branch -a",
            f"cd {git_repo} && git diff HEAD~1",
            f"cd {git_repo} && git show --stat HEAD",
            f"cd {git_repo} && git tag -l",
        ]:
            observer.record_command(cmd)

        # Analyze
        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())

        # Build spec
        builder = SpecBuilder(llm)
        spec = builder.build_from_patterns(patterns)

        # Core assertions
        assert spec.name.lower() == "git", f"Expected name='git', got '{spec.name}'"
        assert "version control" in spec.description.lower() or "git" in spec.description.lower()
        assert len(spec.commands) >= 4, f"Expected >=4 commands, got {len(spec.commands)}"
        assert len(spec.capabilities) >= 1, f"Expected >=1 capabilities, got {len(spec.capabilities)}"

        # Verify key commands present
        cmd_canonicals = {c.canonical.lower() for c in spec.commands}
        for expected in ["git status", "git log", "git branch"]:
            assert any(expected in c for c in cmd_canonicals), \
                f"Expected '{expected}' in commands: {cmd_canonicals}"

        # Verify interaction methods detected
        assert len(spec.interaction_methods) >= 1

        # Save and reload both formats
        spec_json = tmp_path / "git_spec.json"
        spec_yaml = tmp_path / "git_spec.yaml"
        spec.save_json(spec_json)
        spec.save_yaml(spec_yaml)

        reloaded = ToolSpec.load(spec_json)
        assert reloaded.name.lower() == "git"
        assert len(reloaded.commands) == len(spec.commands)

        reloaded_yaml = ToolSpec.load(spec_yaml)
        assert reloaded_yaml.name.lower() == "git"

        print(f"\n{'='*60}")
        print("  PHASE 3: SPECGEN — Claude generated ToolSpec")
        print(f"{'='*60}")
        print(f"  Name:         {spec.name}")
        print(f"  Description:  {spec.description[:80]}")
        print(f"  Commands:     {len(spec.commands)}")
        print(f"  Capabilities: {len(spec.capabilities)}")
        print(f"  Workflows:    {len(spec.workflows)}")
        print(f"  Interactions: {len(spec.interaction_methods)}")
        print(f"  Saved to:     {spec_json}")
        print(f"\n  Commands:")
        for cmd in spec.commands:
            flags = ", ".join(f.flag for f in cmd.flags[:3])
            print(f"    {cmd.canonical} [{flags}]")
            print(f"      → {cmd.description[:70]}")
        print(f"\n  Capabilities:")
        for cap in spec.capabilities:
            print(f"    {cap.name}: {cap.description[:60]}")
        if spec.workflows:
            print(f"\n  Workflows:")
            for wf in spec.workflows:
                print(f"    {wf.name}: {wf.description[:60]}")
        print(f"\n  Interaction methods:")
        for im in spec.interaction_methods:
            auth = f" (auth: {im.auth_type}, env: {im.auth_env_var})" if im.auth_env_var else ""
            print(f"    {im.method}: {im.description[:50]}{auth}")

    def test_phase4_generate_cli(self, git_repo: Path, tmp_path: Path, llm: LLMClient) -> None:
        """Phase 4: Generate a complete CLI from the real spec."""
        # Quick pipeline: observe → analyze → spec
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline",
            f"cd {git_repo} && git branch -a",
            f"cd {git_repo} && git diff HEAD~1",
        ]:
            observer.record_command(cmd)

        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())
        builder = SpecBuilder(llm)
        spec = builder.build_from_patterns(patterns)

        # Generate CLI
        cli_path = tmp_path / "git_cli.py"
        scaffold = CLIScaffold(spec)
        scaffold.generate(cli_path)

        assert cli_path.exists()
        content = cli_path.read_text()

        # Structural checks
        assert "#!/usr/bin/env python3" in content
        assert "TOOL_SPEC" in content
        assert "def ask(" in content
        assert "def cli():" in content
        assert "click" in content

        # Verify valid Python
        result = subprocess.run(
            ["python", "-c", f"import ast; ast.parse(open('{cli_path}').read()); print('VALID')"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error:\n{result.stderr}"
        assert "VALID" in result.stdout

        # Verify executable
        assert os.access(cli_path, os.X_OK)

        print(f"\n{'='*60}")
        print("  PHASE 4: CLIGEN — Generated executable CLI")
        print(f"{'='*60}")
        print(f"  Path:          {cli_path}")
        print(f"  Size:          {cli_path.stat().st_size:,} bytes")
        print(f"  Lines:         {len(content.splitlines())}")
        print(f"  Valid Python:  yes")
        print(f"  Executable:    yes")
        print(f"  Has ask cmd:   yes")
        print(f"  Has TOOL_SPEC: yes")

    def test_phase5_nl_translate_with_claude(self, git_repo: Path, tmp_path: Path, llm: LLMClient) -> None:
        """Phase 5: Translate natural language to git commands using real Claude."""
        # Quick pipeline: observe → analyze → spec
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline",
            f"cd {git_repo} && git branch -a",
            f"cd {git_repo} && git diff HEAD~1",
            f"cd {git_repo} && git tag -l",
        ]:
            observer.record_command(cmd)

        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())
        builder = SpecBuilder(llm)
        spec = builder.build_from_patterns(patterns)

        # NL → Command translation (the core value proposition)
        translator = NLTranslator(llm, spec)

        test_cases = [
            ("show me the commit history", "git log"),
            ("what files have changed", "git"),
            ("list all branches including remote", "git branch"),
            ("show the last 5 commits in one line format", "git log"),
            ("create a new branch called hotfix", "git"),
        ]

        print(f"\n{'='*60}")
        print("  PHASE 5: ASK — Claude NL → Command translation")
        print(f"{'='*60}")

        for nl_input, expected_substr in test_cases:
            commands = translator.translate(nl_input)
            assert len(commands) > 0, f"No commands returned for: '{nl_input}'"
            joined = " ".join(commands).lower()
            assert expected_substr in joined, \
                f"Expected '{expected_substr}' in output for '{nl_input}', got: {commands}"

            print(f'\n  "{nl_input}"')
            for c in commands:
                print(f"    → {c}")

    def test_phase6_execute_safe_commands(self, git_repo: Path, tmp_path: Path, llm: LLMClient) -> None:
        """Phase 6: Execute translated commands safely."""
        # Quick pipeline
        observer = ShellObserver(tmp_path / "session")
        for cmd in [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline",
        ]:
            observer.record_command(cmd)

        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(observer.get_events())
        builder = SpecBuilder(llm)
        spec = builder.build_from_patterns(patterns)

        translator = NLTranslator(llm, spec)
        commands = translator.translate("show me the commit history")
        assert len(commands) > 0

        # Prepend cd to ensure we run in the right directory
        safe_commands = [f"cd {git_repo} && {c}" for c in commands]

        # Dry run first
        dry_executor = Executor(dry_run=True)
        dry_results = dry_executor.run(safe_commands)
        assert all(r.success for r in dry_results)

        # Real execution with auto-confirm
        executor = Executor(auto_confirm=True)
        results = executor.run(safe_commands)
        assert len(results) > 0
        assert results[0].success, f"Command failed: {results[0].command}"

        print(f"\n{'='*60}")
        print("  PHASE 6: EXECUTE — Safe command execution")
        print(f"{'='*60}")
        for r in results:
            status = "OK" if r.success else f"FAIL (exit {r.return_code})"
            cmd_short = r.command.split("&&")[-1].strip()
            print(f"  [{status}] {cmd_short}")


@requires_api_key
class TestRealFullPipeline:
    """Single test that runs the entire pipeline end-to-end with real Claude."""

    def test_complete_pipeline(self, git_repo: Path, tmp_path: Path, llm: LLMClient) -> None:
        """Observe → Analyze → Spec → CLI → Translate → Execute (all real)."""
        print(f"\n{'='*70}")
        print("  COMPLETE REAL E2E PIPELINE: git observation → AI-powered CLI")
        print(f"  Using model: {ANTHROPIC_MODEL}")
        print(f"{'='*70}")

        # ── Step 1: Observe ──────────────────────────────────────────
        observer = ShellObserver(tmp_path / "session")
        git_commands = [
            f"cd {git_repo} && git status",
            f"cd {git_repo} && git log --oneline --all",
            f"cd {git_repo} && git branch -a",
            f"cd {git_repo} && git diff HEAD~1",
            f"cd {git_repo} && git show --stat HEAD",
            f"cd {git_repo} && git tag -l",
            f"cd {git_repo} && git log --oneline --graph --all",
        ]
        for cmd in git_commands:
            event = observer.record_command(cmd)
            assert event.exit_code == 0
        events = observer.get_events()

        print(f"\n  [1/6] OBSERVE — Recorded {len(events)} real git commands")
        for e in events:
            print(f"         {e.command.split('&&')[-1].strip()}")

        # ── Step 2: Analyze ──────────────────────────────────────────
        analyzer = ShellAnalyzer(llm)
        patterns = analyzer.classify_batch(events)
        groups = analyzer.group_by_tool(patterns)

        assert all(p.tool == "git" for p in patterns)
        print(f"\n  [2/6] ANALYZE — Claude classified {len(patterns)} events")
        for p in patterns:
            print(f"         [{p.tool}] {p.operation}: {p.description[:60]}")

        # ── Step 3: Build Spec ───────────────────────────────────────
        builder = SpecBuilder(llm)
        spec = builder.build_from_patterns(patterns)
        spec_path = tmp_path / "git_spec.json"
        spec.save_json(spec_path)

        assert spec.name.lower() == "git"
        assert len(spec.commands) >= 4
        print(f"\n  [3/6] SPEC — Generated '{spec.name}' with {len(spec.commands)} commands, "
              f"{len(spec.capabilities)} capabilities")
        for cmd in spec.commands:
            print(f"         {cmd.canonical}: {cmd.description[:55]}")

        # ── Step 4: Generate CLI ─────────────────────────────────────
        cli_path = tmp_path / "git_cli.py"
        scaffold = CLIScaffold(spec)
        scaffold.generate(cli_path)

        result = subprocess.run(
            ["python", "-c", f"import ast; ast.parse(open('{cli_path}').read())"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        print(f"\n  [4/6] CLI — Generated {cli_path.stat().st_size:,}-byte CLI (valid Python)")

        # ── Step 5: NL → Commands ────────────────────────────────────
        translator = NLTranslator(llm, spec)
        nl_tests = [
            ("show me the commit history", "git log"),
            ("what branches exist", "git branch"),
            ("show changes in the last commit", "git"),
            ("list all tags", "git tag"),
        ]

        print(f"\n  [5/6] ASK — NL → Command translation (real Claude):")
        for nl_input, expected in nl_tests:
            commands = translator.translate(nl_input)
            assert len(commands) > 0
            joined = " ".join(commands).lower()
            assert expected in joined, f"'{expected}' not in {commands}"
            print(f'         "{nl_input}"')
            print(f"           → {commands[0]}")

        # ── Step 6: Execute ──────────────────────────────────────────
        commands = translator.translate("show me the commit log in one line format")
        assert len(commands) > 0
        safe_commands = [f"cd {git_repo} && {c}" for c in commands]
        executor = Executor(auto_confirm=True)
        results = executor.run(safe_commands)
        assert results[0].success

        print(f"\n  [6/6] EXECUTE — Ran translated command successfully")
        for r in results:
            status = "OK" if r.success else "FAIL"
            print(f"         [{status}] {r.command.split('&&')[-1].strip()}")

        # ── Summary ──────────────────────────────────────────────────
        print(f"\n{'='*70}")
        print(f"  PIPELINE COMPLETE (all real Claude API calls)")
        print(f"  Observed:     {len(events)} commands")
        print(f"  Classified:   {len(patterns)} patterns")
        print(f"  Spec:         {spec.name} — {len(spec.commands)} cmds, "
              f"{len(spec.capabilities)} caps, {len(spec.workflows)} workflows")
        print(f"  CLI:          {cli_path} ({cli_path.stat().st_size:,} bytes)")
        print(f"  Spec file:    {spec_path}")
        print(f"  NL queries:   {len(nl_tests)} translated successfully")
        print(f"  Executed:     {sum(1 for r in results if r.success)}/{len(results)} commands")
        print(f"{'='*70}")

        # Print the generated spec for inspection
        print(f"\n  --- Generated ToolSpec (JSON) ---")
        spec_data = json.loads(spec_path.read_text())
        print(json.dumps(spec_data, indent=2)[:3000])
