"""CLIaS main CLI — observe, analyze, generate, ask."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from clias import __version__
from clias.config import Config

console = Console()


@click.group()
@click.version_option(version=__version__)
@click.option("--config", "-c", type=click.Path(exists=False), default=None, help="Config file path.")
@click.pass_context
def main(ctx: click.Context, config: str | None) -> None:
    """CLIaS — Turn any observed software into an AI-powered CLI assistant."""
    ctx.ensure_object(dict)
    cfg_path = Path(config) if config else None
    ctx.obj["config"] = Config.load(cfg_path)


# ---------------------------------------------------------------------------
# observe — record a shell (and optionally screen) session
# ---------------------------------------------------------------------------
@main.command()
@click.option("--output", "-o", type=click.Path(), default="./clias_sessions", help="Output directory.")
@click.option("--screen", is_flag=True, help="Also capture screenshots.")
@click.option("--command", "-C", multiple=True, help="Run specific commands instead of interactive session.")
@click.pass_context
def observe(ctx: click.Context, output: str, screen: bool, command: tuple[str, ...]) -> None:
    """Record a shell session (and optionally the screen) for later analysis."""
    from clias.observer.session import Session

    cfg = ctx.obj["config"]
    session = Session(
        output_dir=Path(output),
        enable_screen=screen,
        screenshot_interval=cfg.observer.screenshot_interval,
    )

    if command:
        for cmd in command:
            console.print(f"[dim]$ {cmd}[/dim]")
            event = session.record_command(cmd)
            if event.exit_code != 0:
                console.print(f"[yellow]exit {event.exit_code}[/yellow]")
    else:
        session.record_interactive()

    manifest = session.finalize()
    console.print(f"\n[green]Session saved:[/green] {session.session_dir}")
    console.print(f"  Shell events: {manifest.shell_event_count}")
    if screen:
        console.print(f"  Screenshots:  {manifest.screenshot_count}")


# ---------------------------------------------------------------------------
# analyze — process a recorded session into a ToolSpec
# ---------------------------------------------------------------------------
@main.command()
@click.argument("session_dir", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output spec file path.")
@click.option("--format", "fmt", type=click.Choice(["json", "yaml"]), default="json")
@click.option("--vision/--no-vision", default=False, help="Include screenshot analysis.")
@click.pass_context
def analyze(ctx: click.Context, session_dir: str, output: str | None, fmt: str, vision: bool) -> None:
    """Analyze a recorded session and produce a ToolSpec."""
    from clias.observer.session import SessionManifest
    from clias.observer.shell import ShellObserver
    from clias.analyzer.shell import ShellAnalyzer
    from clias.analyzer.vision import VisionAnalyzer
    from clias.analyzer.merger import CrossReferenceMerger
    from clias.specgen.builder import SpecBuilder
    from clias.llm.client import LLMClient

    cfg = ctx.obj["config"]
    llm = LLMClient(cfg.llm)
    session_path = Path(session_dir)

    # Load shell events
    manifest_file = session_path / "manifest.json"
    events_file = session_path / "shell_events.jsonl"

    if not events_file.exists():
        console.print("[red]No shell_events.jsonl found in session directory.[/red]")
        raise SystemExit(1)

    events = ShellObserver.load_events(events_file)
    console.print(f"Loaded {len(events)} shell events.")

    # Analyze shell events
    shell_analyzer = ShellAnalyzer(llm)
    console.print("Classifying shell commands...")
    patterns = shell_analyzer.classify_batch(events)
    console.print(f"  → {len(patterns)} patterns identified.")

    # Optional vision analysis
    spec_builder = SpecBuilder(llm)
    if vision:
        screenshots_dir = session_path / "screenshots"
        if screenshots_dir.exists():
            frames = sorted(screenshots_dir.glob("frame_*.png"))
            if frames:
                console.print(f"Analyzing {len(frames)} screenshots...")
                vision_analyzer = VisionAnalyzer(llm)
                ui_actions = vision_analyzer.analyze_screenshots(frames)
                console.print(f"  → {len(ui_actions)} UI actions detected.")

                console.print("Cross-referencing shell and UI data...")
                merger = CrossReferenceMerger(llm)
                correlated = merger.merge(patterns, ui_actions)
                spec = spec_builder.build_from_correlated(correlated)
            else:
                console.print("[yellow]No screenshots found, proceeding with shell-only analysis.[/yellow]")
                spec = spec_builder.build_from_patterns(patterns)
        else:
            spec = spec_builder.build_from_patterns(patterns)
    else:
        spec = spec_builder.build_from_patterns(patterns)

    # Save spec
    if output is None:
        output = str(session_path / f"tool_spec.{fmt}")

    out_path = Path(output)
    if fmt == "yaml":
        spec.save_yaml(out_path)
    else:
        spec.save_json(out_path)

    console.print(f"\n[green]Spec saved:[/green] {out_path}")
    console.print(f"  Tool:         {spec.name}")
    console.print(f"  Commands:     {len(spec.commands)}")
    console.print(f"  Capabilities: {len(spec.capabilities)}")
    console.print(f"  Workflows:    {len(spec.workflows)}")
    if spec.interaction_methods:
        console.print(f"  Interaction:  {', '.join(m.method for m in spec.interaction_methods)}")


# ---------------------------------------------------------------------------
# generate — produce a CLI from a ToolSpec
# ---------------------------------------------------------------------------
@main.command()
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output CLI script path.")
@click.pass_context
def generate(ctx: click.Context, spec_file: str, output: str | None) -> None:
    """Generate a standalone CLI from a ToolSpec file."""
    from clias.specgen.schema import ToolSpec
    from clias.cligen.scaffold import CLIScaffold

    spec = ToolSpec.load(Path(spec_file))

    if output is None:
        output = f"./{spec.name}_cli.py"

    scaffold = CLIScaffold(spec)
    out_path = scaffold.generate(Path(output))
    console.print(f"\n[green]CLI generated:[/green] {out_path}")
    console.print(f"  Run with: python {out_path} --help")
    console.print(f"  Or:       python {out_path} ask 'your request here'")


# ---------------------------------------------------------------------------
# ask — quick one-shot NL→command translation using an existing spec
# ---------------------------------------------------------------------------
@main.command()
@click.argument("spec_file", type=click.Path(exists=True))
@click.argument("request", nargs=-1, required=True)
@click.option("--execute", "-x", is_flag=True, help="Execute immediately.")
@click.option("--dry-run", "-n", is_flag=True, help="Show commands only.")
@click.pass_context
def ask(ctx: click.Context, spec_file: str, request: tuple[str, ...], execute: bool, dry_run: bool) -> None:
    """Translate a natural language request into commands using a ToolSpec."""
    from clias.specgen.schema import ToolSpec
    from clias.cligen.translator import NLTranslator
    from clias.cligen.executor import Executor
    from clias.llm.client import LLMClient

    cfg = ctx.obj["config"]
    llm = LLMClient(cfg.llm)
    spec = ToolSpec.load(Path(spec_file))
    user_input = " ".join(request)

    translator = NLTranslator(llm, spec)
    commands = translator.translate(user_input)

    if not commands:
        console.print("[yellow]No commands generated.[/yellow]")
        return

    executor = Executor(auto_confirm=execute, dry_run=dry_run)
    executor.run(commands)


# ---------------------------------------------------------------------------
# merge — combine multiple specs
# ---------------------------------------------------------------------------
@main.command()
@click.argument("spec_files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), required=True, help="Output merged spec path.")
@click.option("--format", "fmt", type=click.Choice(["json", "yaml"]), default="json")
def merge(spec_files: tuple[str, ...], output: str, fmt: str) -> None:
    """Merge multiple ToolSpec files into one."""
    from clias.specgen.schema import ToolSpec

    specs = [ToolSpec.load(Path(f)) for f in spec_files]
    if not specs:
        console.print("[red]No specs provided.[/red]")
        raise SystemExit(1)

    base = specs[0]
    for other in specs[1:]:
        base.merge(other)

    out_path = Path(output)
    if fmt == "yaml":
        base.save_yaml(out_path)
    else:
        base.save_json(out_path)

    console.print(f"[green]Merged spec saved:[/green] {out_path}")
