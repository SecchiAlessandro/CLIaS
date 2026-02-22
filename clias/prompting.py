"""Interactive credential prompting for missing API credentials."""

from __future__ import annotations

import os

from rich.console import Console
from rich.prompt import Prompt


def ask_user_credentials(
    missing: list[dict],
    console: Console,
) -> dict[str, str]:
    """Prompt user for missing API credentials.

    Args:
        missing: List of dicts with keys: env_var, service, reason.
        console: Rich console for output.

    Returns:
        Dict of {env_var: value} for credentials the user provided.
        Sets accepted values in os.environ for the current session.
        Never logs or stores the actual secret values.
    """
    if not missing:
        return {}

    console.print(
        "\n[yellow bold]Missing credentials detected[/yellow bold]"
    )
    console.print(
        "The following API credentials are referenced in commands "
        "but not found in your environment:\n"
    )
    for item in missing:
        console.print(
            f"  [cyan]${item['env_var']}[/cyan] — {item['service']} "
            f"({item['reason']})"
        )
    console.print()

    provided: dict[str, str] = {}
    for item in missing:
        value = Prompt.ask(
            f"  Enter [cyan]${item['env_var']}[/cyan] "
            f"(or press Enter to skip)",
            default="",
            console=console,
        )
        if value:
            os.environ[item["env_var"]] = value
            provided[item["env_var"]] = value

    if provided:
        console.print(
            f"\n[green]{len(provided)} credential(s) set for this session.[/green]"
        )
    else:
        console.print("\n[dim]No credentials provided, continuing...[/dim]")

    return provided
