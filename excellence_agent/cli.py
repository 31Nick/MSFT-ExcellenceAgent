"""Click CLI entry point for the ExcellenceAgent."""

from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path

import click

from excellence_agent import __version__

logger = logging.getLogger(__name__)

# Default matrix path: project root / resource_matrix.yaml
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MATRIX = str(_PROJECT_ROOT / "resource_matrix.yaml")


# ---------------------------------------------------------------------------
# Shared option helpers
# ---------------------------------------------------------------------------

def _report_option(fn):
    """Common ``--report`` option for commands that need an APRL Excel path."""
    return click.option(
        "--report",
        required=True,
        type=click.Path(exists=True, dir_okay=False),
        help="Path to the APRL v2 Excel report.",
    )(fn)


def _advisor_option(fn):
    """Optional ``--advisor`` option for Advisor CSV path."""
    return click.option(
        "--advisor",
        required=False,
        default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Optional path to Azure Advisor CSV export.",
    )(fn)


def _elapsed(start: float) -> str:
    return f"{time.time() - start:.2f}s"


def _load_advisor_type_mapping(matrix_path: str) -> dict[str, str]:
    """Load the advisor_type_mapping from a resource matrix YAML file."""
    import yaml
    with open(matrix_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("advisor_type_mapping", {})


def _export_ado(hierarchy, output: str, area_path: str, iteration_path: str) -> None:
    """Export to ADO CSV format."""
    from excellence_agent.config import ADOConfig
    from excellence_agent.export.ado_csv import ADOExporter
    from excellence_agent.export.content_generator import ContentGenerator

    click.echo(click.style("▶ Exporting to ADO CSV …", fg="cyan"))
    ado_config = ADOConfig(area_path=area_path, iteration_path=iteration_path)
    content_gen = ContentGenerator()
    exporter = ADOExporter(config=ado_config, content_generator=content_gen)

    try:
        out_path = exporter.export(hierarchy, output)
    except Exception as exc:
        raise click.ClickException(f"Export failed: {exc}") from exc

    click.echo(click.style(f"\n✔ CSV exported to {out_path}", fg="green"))


def _export_github(hierarchy, output: str | None, repo: str, milestone: str, assignee: str) -> None:
    """Export to GitHub Issues format (JSON + Markdown)."""
    from excellence_agent.config import GitHubConfig
    from excellence_agent.export.github_content import GitHubContentGenerator
    from excellence_agent.export.github_export import GitHubExporter

    if not repo:
        raise click.ClickException("--repo is required for GitHub export (e.g. owner/repo).")

    click.echo(click.style("▶ Exporting to GitHub Issues format …", fg="cyan"))
    github_config = GitHubConfig(repo=repo, milestone=milestone, assignee=assignee)
    content_gen = GitHubContentGenerator()
    exporter = GitHubExporter(config=github_config, content_generator=content_gen)

    output_dir = output or "output"
    try:
        paths = exporter.export(hierarchy, output_dir)
    except Exception as exc:
        raise click.ClickException(f"Export failed: {exc}") from exc

    click.echo(click.style(f"\n✔ GitHub export complete", fg="green"))
    click.echo(f"  JSON:     {paths['json_path']}")
    click.echo(f"  Markdown: {paths['markdown_path']}")


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version=__version__, prog_name="excellence-agent")
@click.option("-v", "--verbose", is_flag=True, help="Enable DEBUG logging.")
def cli(verbose: bool) -> None:
    """ExcellenceAgent — APRL-to-ADO work-item pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

@cli.command()
@_report_option
@_advisor_option
def ingest(report: str, advisor: str | None) -> None:
    """Parse an APRL report and display a summary."""
    from excellence_agent.ingest import APRLParser

    start = time.time()
    click.echo(click.style("▶ Parsing APRL report …", fg="cyan"))

    try:
        parser = APRLParser(report)
        aprl = parser.parse()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    df = aprl.impacted_resources
    row_count = len(df)

    unique_types = df["Resource Type"].nunique() if "Resource Type" in df.columns else 0
    unique_recs = (
        df["Recommendation Title"].nunique()
        if "Recommendation Title" in df.columns
        else 0
    )

    impact_breakdown: dict[str, int] = {}
    if "Impact" in df.columns:
        impact_breakdown = dict(Counter(df["Impact"].dropna()))

    click.echo(click.style("\n✔ Ingest complete", fg="green"))
    click.echo(f"  Rows:                   {row_count}")
    click.echo(f"  Platform-issue rows:    {len(aprl.platform_issues)}")
    click.echo(f"  Unique resource types:  {unique_types}")
    click.echo(f"  Unique recommendations: {unique_recs}")

    if impact_breakdown:
        click.echo(click.style("  Impact breakdown:", fg="cyan"))
        for impact, count in sorted(
            impact_breakdown.items(),
            key=lambda kv: {"High": 1, "Medium": 2, "Low": 3}.get(kv[0], 4),
        ):
            click.echo(f"    {impact}: {count}")

    if advisor:
        from excellence_agent.ingest import AdvisorParser
        click.echo(click.style("▶ Parsing Advisor CSV …", fg="cyan"))
        type_mapping = _load_advisor_type_mapping(_DEFAULT_MATRIX)
        advisor_parser = AdvisorParser(advisor, type_mapping=type_mapping)
        advisor_report = advisor_parser.parse()
        advisor_df = advisor_report.recommendations
        click.echo(f"  Advisor rows:           {len(advisor_df)}")
        advisor_types = advisor_df["Type"].nunique() if "Type" in advisor_df.columns else 0
        click.echo(f"  Advisor resource types: {advisor_types}")

    click.echo(f"\n  Elapsed: {_elapsed(start)}")


# ---------------------------------------------------------------------------
# analyse
# ---------------------------------------------------------------------------

@cli.command()
@_report_option
@_advisor_option
@click.option(
    "--matrix",
    default=_DEFAULT_MATRIX,
    type=click.Path(exists=True, dir_okay=False),
    show_default=True,
    help="Path to resource_matrix.yaml.",
)
def analyse(report: str, matrix: str, advisor: str | None) -> None:
    """Run the full analysis pipeline on an APRL report."""
    from excellence_agent.analysis import (
        Deduplicator,
        HierarchyBuilder,
        PatternDetector,
        ResourceMapper,
    )
    from excellence_agent.ingest import APRLParser

    start = time.time()
    click.echo(click.style("▶ Parsing APRL report …", fg="cyan"))

    try:
        aprl = APRLParser(report).parse()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    df = aprl.impacted_resources

    # Optional Advisor merge
    xref_report = None
    if advisor:
        from excellence_agent.ingest import AdvisorParser
        from excellence_agent.analysis import CrossReferencer

        click.echo(click.style("▶ Parsing Advisor CSV …", fg="cyan"))
        type_mapping = _load_advisor_type_mapping(matrix)
        advisor_report = AdvisorParser(advisor, type_mapping=type_mapping).parse()

        click.echo(click.style("▶ Cross-referencing APRL + Advisor …", fg="cyan"))
        xref = CrossReferencer()
        df, xref_report = xref.merge(df, advisor_report.recommendations)
        click.echo(xref_report.summary())

    # Map (use df which may be merged)
    click.echo(click.style("▶ Mapping resources …", fg="cyan"))
    mapper = ResourceMapper.from_yaml(matrix)
    df = mapper.map_dataframe(df)

    # Build hierarchy
    click.echo(click.style("▶ Building hierarchy …", fg="cyan"))
    descriptions = {
        cat: info["description"]
        for cat, info in mapper.get_mapping_summary().items()
    }
    hierarchy = HierarchyBuilder(category_descriptions=descriptions).build(df)

    # Deduplication
    click.echo(click.style("▶ Deduplication analysis …", fg="cyan"))
    dedup_report = Deduplicator().analyse(hierarchy)
    click.echo(dedup_report.summary())

    # Pattern detection
    click.echo(click.style("\n▶ Pattern detection …", fg="cyan"))
    patterns = PatternDetector().detect(hierarchy)
    if patterns:
        for p in patterns:
            click.echo(
                click.style(f"  ● {p.name}", fg="yellow")
                + f"  — {p.description}"
            )
    else:
        click.echo("  No cross-cutting patterns detected.")

    # Hierarchy summary
    stats = hierarchy.summary_stats()
    click.echo(click.style("\n✔ Analysis complete", fg="green"))
    click.echo(f"  Epics:        {stats['epics']}")
    click.echo(f"  Features:     {stats['features']}")
    click.echo(f"  User Stories: {stats['user_stories']}")
    click.echo(f"  Tasks:        {stats['tasks']}")
    click.echo(f"\n  Elapsed: {_elapsed(start)}")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@cli.command()
@_report_option
@_advisor_option
@click.option(
    "--matrix",
    default=_DEFAULT_MATRIX,
    type=click.Path(exists=True, dir_okay=False),
    show_default=True,
    help="Path to resource_matrix.yaml.",
)
@click.option(
    "--target",
    type=click.Choice(["ado", "github"], case_sensitive=False),
    default="ado",
    show_default=True,
    help="Export target platform.",
)
@click.option(
    "--output",
    default=None,
    help="Output path. Defaults to output/ado_import.csv (ADO) or output/ directory (GitHub).",
)
@click.option("--area-path", default="", help="ADO Area Path (ADO target only).")
@click.option("--iteration-path", default="", help="ADO Iteration Path (ADO target only).")
@click.option("--repo", default="", help="GitHub repository as owner/repo (GitHub target only).")
@click.option("--milestone", default="", help="GitHub milestone name (GitHub target only).")
@click.option("--assignee", default="", help="GitHub default assignee (GitHub target only).")
def export(
    report: str,
    matrix: str,
    target: str,
    output: str | None,
    area_path: str,
    iteration_path: str,
    repo: str,
    milestone: str,
    assignee: str,
    advisor: str | None,
) -> None:
    """Run analysis and export work items to ADO CSV or GitHub Issues format."""
    from excellence_agent.analysis import (
        HierarchyBuilder,
        ResourceMapper,
    )
    from excellence_agent.ingest import APRLParser

    start = time.time()
    click.echo(click.style("▶ Parsing APRL report …", fg="cyan"))

    try:
        aprl = APRLParser(report).parse()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    df = aprl.impacted_resources

    if advisor:
        from excellence_agent.ingest import AdvisorParser
        from excellence_agent.analysis import CrossReferencer

        click.echo(click.style("▶ Parsing Advisor CSV …", fg="cyan"))
        type_mapping = _load_advisor_type_mapping(matrix)
        advisor_report = AdvisorParser(advisor, type_mapping=type_mapping).parse()

        click.echo(click.style("▶ Cross-referencing …", fg="cyan"))
        xref = CrossReferencer()
        df, xref_report = xref.merge(df, advisor_report.recommendations)
        click.echo(f"  Merged: {xref_report.total_merged_rows} rows ({len(xref_report.matched_resources)} matched resources)")

    # Map
    click.echo(click.style("▶ Mapping resources …", fg="cyan"))
    mapper = ResourceMapper.from_yaml(matrix)
    df = mapper.map_dataframe(df)

    # Build hierarchy
    click.echo(click.style("▶ Building hierarchy …", fg="cyan"))
    descriptions = {
        cat: info["description"]
        for cat, info in mapper.get_mapping_summary().items()
    }
    hierarchy = HierarchyBuilder(category_descriptions=descriptions).build(df)

    # Export based on target
    if target == "github":
        _export_github(hierarchy, output, repo, milestone, assignee)
    else:
        _export_ado(hierarchy, output or "output/ado_import.csv", area_path, iteration_path)

    stats = hierarchy.summary_stats()
    click.echo(f"  Epics:        {stats['epics']}")
    click.echo(f"  Features:     {stats['features']}")
    click.echo(f"  User Stories: {stats['user_stories']}")
    click.echo(f"  Tasks:        {stats['tasks']}")
    click.echo(f"\n  Elapsed: {_elapsed(start)}")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--port", default=5000, show_default=True, help="Port for the web dashboard.")
def serve(port: int) -> None:
    """Start the ExcellenceAgent web dashboard."""
    click.echo(click.style(f"▶ Starting web dashboard on port {port} …", fg="cyan"))

    try:
        from excellence_agent.web.app import create_app
    except ImportError as exc:
        raise click.ClickException(
            f"Web module not available — install web extras: {exc}"
        ) from exc

    app = create_app()
    app.run(host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
