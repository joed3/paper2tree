"""Paper2Tree CLI.

Usage:
  python -m src.main process <url> [--force]
  python -m src.main batch <urls_file> [--force] [--concurrency N]
  python -m src.main list [--sort-by title|date|score]
  python -m src.main show <paper_id>
"""

import asyncio
import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .orchestrator import OUTPUTS_DIR, process_paper

console = Console()


@click.group()
def cli() -> None:
    """Paper2Tree — multi-agent scientific paper review system."""


# ── process ───────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("url")
@click.option("--force", is_flag=True, help="Reprocess even if already cached.")
def process(url: str, force: bool) -> None:
    """Process a paper URL and build its claim DAG."""
    try:
        asyncio.run(process_paper(url, force=force))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


# ── batch ─────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("urls_file", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Reprocess already-cached papers.")
@click.option("--concurrency", default=1, show_default=True, help="Max concurrent papers.")
def batch(urls_file: str, force: bool, concurrency: int) -> None:
    """Process multiple papers from a file (one URL per line, # for comments)."""
    lines = Path(urls_file).read_text().splitlines()
    urls = [line.strip() for line in lines if line.strip() and not line.startswith("#")]

    if not urls:
        console.print("[yellow]No URLs found in file.[/yellow]")
        return

    console.print(f"Processing {len(urls)} paper(s) (concurrency={concurrency}) …\n")

    async def run() -> None:
        sem = asyncio.Semaphore(concurrency)

        async def process_one(url: str) -> None:
            async with sem:
                try:
                    paper_id = await process_paper(url, force=force)
                    console.print(f"[green]✓[/green] {paper_id}  {url}")
                except Exception as e:
                    console.print(f"[red]✗[/red] {url}\n  [dim]{e}[/dim]")

        await asyncio.gather(*[process_one(u) for u in urls])

    asyncio.run(run())


# ── list ──────────────────────────────────────────────────────────────────────


@cli.command("list")
@click.option(
    "--sort-by",
    default="date",
    show_default=True,
    type=click.Choice(["title", "date", "score"]),
    help="Sort order.",
)
def list_papers(sort_by: str) -> None:
    """List all processed papers."""
    index_path = OUTPUTS_DIR / "index.json"
    if not index_path.exists():
        console.print(
            "[yellow]No papers processed yet. Run 'process <url>' to get started.[/yellow]"
        )
        return

    data = json.loads(index_path.read_text())
    papers = data.get("papers", [])

    if not papers:
        console.print("[yellow]No papers in index.[/yellow]")
        return

    if sort_by == "title":
        papers.sort(key=lambda p: p["title"].lower())
    elif sort_by == "score":
        papers.sort(key=lambda p: p["mean_validity_score"], reverse=True)
    # "date" is the default sort from the index (newest first)

    table = Table(title=f"Processed Papers ({len(papers)} total)", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", max_width=50)
    table.add_column("Authors", max_width=28)
    table.add_column("Claims", justify="right", width=7)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Date", width=10)
    table.add_column("ID", style="dim", max_width=36)

    for i, p in enumerate(papers, 1):
        score = p["mean_validity_score"]
        score_text = Text(f"{score:.2f}")
        if score >= 0.8:
            score_text.stylize("green")
        elif score >= 0.5:
            score_text.stylize("yellow")
        else:
            score_text.stylize("red")

        authors = p.get("authors", [])
        author_str = ", ".join(authors[:2])
        if len(authors) > 2:
            author_str += f" +{len(authors) - 2}"

        table.add_row(
            str(i),
            p["title"],
            author_str,
            str(p["total_claims"]),
            score_text,
            p["processed_at"][:10],
            p["paper_id"],
        )

    console.print(table)


# ── show ──────────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("paper_id")
def show(paper_id: str) -> None:
    """Show the summary for a processed paper."""
    dag_path = OUTPUTS_DIR / paper_id / "dag.json"
    if not dag_path.exists():
        console.print(f"[red]Paper not found:[/red] {paper_id}")
        sys.exit(1)

    data = json.loads(dag_path.read_text())
    paper = data["paper"]
    summary = data["summary"]
    nodes = data["dag"]["nodes"]

    score = summary["mean_validity_score"]
    score_color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"

    console.print(
        Panel(
            f"[bold]{paper['title']}[/bold]\n"
            f"[dim]{', '.join(paper['authors'])}[/dim]\n\n"
            f"{paper['abstract'][:400]}{'…' if len(paper['abstract']) > 400 else ''}",
            title="Paper",
        )
    )

    console.print(
        f"\n[bold]Summary:[/bold]  "
        f"{summary['total_nodes']} claims  |  "
        f"max depth {summary['max_depth']}  |  "
        f"mean score [{score_color}]{score:.2f}[/{score_color}]  |  "
        f"{summary['high_confidence_nodes']} high / {summary['low_confidence_nodes']} low confidence\n"
    )
    console.print(f"[dim]{summary['overall_assessment']}[/dim]\n")

    # Print claim tree
    claim_table = Table(title="Claims", show_lines=False, show_header=True)
    claim_table.add_column("ID", style="dim", width=12)
    claim_table.add_column("Type", width=10)
    claim_table.add_column("Claim", max_width=70)
    claim_table.add_column("Score", justify="right", width=7)

    root_first = sorted(nodes, key=lambda n: (n["depth"], n["id"]))
    for node in root_first:
        indent = "  " * node["depth"]
        eval_ = node.get("evaluation") or {}
        s = eval_.get("validity_score", None)
        s_text = Text(f"{s:.2f}" if s is not None else "—")
        if s is not None:
            s_text.stylize("green" if s >= 0.8 else "yellow" if s >= 0.5 else "red")

        claim_table.add_row(
            indent + node["id"],
            node["type"],
            node["label"],
            s_text,
        )

    console.print(claim_table)


if __name__ == "__main__":
    cli()
