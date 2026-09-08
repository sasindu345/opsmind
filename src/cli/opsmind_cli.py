"""OpsMind interactive terminal CLI using Typer and Rich."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.api.schemas import LogBatch
from src.core.pipeline import analyze_logs
from src.core.worker import IncidentWorker
from src.infrastructure.factory import get_incident_repository

app = typer.Typer(
    name="opsmind",
    help="OpsMind: AI-Driven Platform Engineering and Incident Triage CLI.",
    add_completion=False,
)
console = Console()


@app.command(name="triage")
def triage_cmd(
    service: Annotated[str, typer.Option("--service", "-s", help="Target service name")],
    logs_file: Annotated[
        Path | None, typer.Option("--file", "-f", help="Path to raw log file")
    ] = None,
    environment: Annotated[
        str, typer.Option("--env", "-e", help="Environment name")
    ] = "production",
) -> None:
    """Run interactive root-cause triage on a set of log lines."""
    console.print(
        f"[bold cyan]🔍 OpsMind Triage Initiated[/bold cyan] for service: "
        f"[bold green]{service}[/bold green]"
    )

    logs: list[str] = []
    if logs_file and logs_file.exists():
        raw_lines = logs_file.read_text(encoding="utf-8").splitlines()
        logs = [line.strip() for line in raw_lines if line.strip()]
    else:
        logs = [
            f"ERROR OOMKilled pod {service}-7f89b memory limit exceeded",
            f"ERROR Connection pool exhausted for {service} DB",
            f"WARN HTTP 504 gateway timeout on {service}/api/checkout",
        ]

    batch = LogBatch(service=service, environment=environment, logs=logs, generate_report=True)

    with console.status("[bold yellow]Clustering logs and reasoning root cause...[/bold yellow]"):
        result = asyncio.run(analyze_logs(batch))

    sev_color = {
        "critical": "red",
        "high": "orange3",
        "medium": "yellow",
        "low": "blue",
    }.get(result.analysis.severity.value, "white")

    verdict_text = (
        f"[bold {sev_color}]{result.analysis.severity.emoji} Severity: "
        f"{result.analysis.severity.value.upper()}[/bold {sev_color}]\n"
        f"[bold]Incident ID:[/bold] {result.incident_id}\n"
        f"[bold]Probable Cause:[/bold] {result.analysis.probable_cause}\n"
        f"[bold]Confidence:[/bold] {int(result.analysis.confidence * 100)}%\n"
        f"[bold]Summary:[/bold] {result.analysis.summary}"
    )

    console.print(
        Panel.fit(
            verdict_text,
            title=f"Incident Analysis Verdict — {service}",
            border_style=sev_color,
        )
    )

    if result.observed_evidence:
        console.print("[bold]Observed Evidence:[/bold]")
        for ev in result.observed_evidence[:4]:
            console.print(f"  • {ev}")

    if result.report_path:
        console.print(
            f"\n[green]📄 Post-mortem report written to:[/green] "
            f"[underline]{result.report_path}[/underline]"
        )


@app.command(name="incidents")
def list_incidents_cmd(
    service: Annotated[
        str | None, typer.Option("--service", "-s", help="Filter by service name")
    ] = None,
    status_filter: Annotated[
        str | None, typer.Option("--status", help="Filter by status (open, acknowledged, resolved)")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max records to display")] = 10,
) -> None:
    """List recent incidents stored in repository."""
    repo = get_incident_repository()
    records = asyncio.run(repo.list_incidents(service=service, status=status_filter, limit=limit))

    if not records:
        console.print("[yellow]No incidents found in repository.[/yellow]")
        return

    table = Table(title="OpsMind Recorded Incidents", header_style="bold magenta")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Service", style="green")
    table.add_column("Severity", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Probable Cause", style="white")
    table.add_column("Time", style="dim")

    for r in records:
        sev_style = "red" if r.severity in {"critical", "high"} else "yellow"
        table.add_row(
            r.incident_id[:8],
            r.service,
            f"[{sev_style}]{r.severity.upper()}[/{sev_style}]",
            r.status.upper(),
            r.probable_cause[:50] + "..." if len(r.probable_cause) > 50 else r.probable_cause,
            r.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


@app.command(name="explain")
def explain_cmd(incident_id: Annotated[str, typer.Argument(help="Incident ID to explain")]) -> None:
    """Display root-cause breakdown and timeline for an incident."""
    repo = get_incident_repository()
    record = asyncio.run(repo.get_incident(incident_id))

    if not record:
        console.print(f"[red]Error: Incident '{incident_id}' not found.[/red]")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold]Service:[/bold] {record.service} ({record.environment})\n"
            f"[bold]Status:[/bold] {record.status.upper()}\n"
            f"[bold]Severity:[/bold] {record.severity.upper()}\n"
            f"[bold]Root Cause:[/bold] {record.probable_cause}\n"
            f"[bold]Confidence:[/bold] {int(record.confidence * 100)}%",
            title=f"Incident Explanation: {record.incident_id[:8]}",
            border_style="cyan",
        )
    )

    if record.timeline_json:
        console.print("\n[bold cyan]Timeline Events:[/bold cyan]")
        for t in record.timeline_json:
            ts = t.get("timestamp", "")[:19]
            src = t.get("source", "")
            desc = t.get("description", "")
            console.print(f"  • [dim]{ts}[/dim] [{src}] {desc}")


@app.command(name="worker")
def run_worker_cmd(
    poll_interval: Annotated[
        float, typer.Option("--interval", "-i", help="Poll interval in seconds")
    ] = 0.5,
) -> None:
    """Start the asynchronous incident queue worker daemon."""
    console.print(
        "[bold green]Starting OpsMind Incident Worker Daemon...[/bold green] (Press Ctrl+C to stop)"
    )
    worker = IncidentWorker()
    try:
        asyncio.run(worker.run_loop(poll_interval=poll_interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]Worker stopped by user.[/yellow]")


if __name__ == "__main__":
    app()
