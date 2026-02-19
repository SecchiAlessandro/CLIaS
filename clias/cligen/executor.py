"""Runtime executor — safely runs commands with confirmation and streaming output."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.prompt import Confirm


console = Console()


@dataclass
class ExecutionResult:
    command: str
    return_code: int
    success: bool


class Executor:
    """Runs shell commands with a confirmation gate and real-time output streaming."""

    def __init__(self, auto_confirm: bool = False, dry_run: bool = False) -> None:
        self.auto_confirm = auto_confirm
        self.dry_run = dry_run

    def run(self, commands: list[str]) -> list[ExecutionResult]:
        results = []
        for cmd in commands:
            result = self._run_one(cmd)
            results.append(result)
            if not result.success:
                console.print(f"[red]Command failed (exit {result.return_code}). Stopping.[/red]")
                break
        return results

    def _run_one(self, command: str) -> ExecutionResult:
        console.print(f"\n[bold]Command:[/bold] [cyan]{command}[/cyan]")

        if self.dry_run:
            console.print("[dim](dry run — not executed)[/dim]")
            return ExecutionResult(command=command, return_code=0, success=True)

        if not self.auto_confirm:
            if not Confirm.ask("Execute?", default=False):
                console.print("[dim]Skipped.[/dim]")
                return ExecutionResult(command=command, return_code=-1, success=True)

        console.print("[dim]Running...[/dim]")
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        output_lines = []
        for line in proc.stdout:  # type: ignore[union-attr]
            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line)

        proc.wait()
        return ExecutionResult(
            command=command,
            return_code=proc.returncode,
            success=proc.returncode == 0,
        )
