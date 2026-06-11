"""Click CLI entry point for the ExcellenceAgent."""

from __future__ import annotations

import asyncio
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
    click.echo(f"  Recommendations: {stats['recommendations']}")
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
    "--output",
    default="output/ado_import.csv",
    show_default=True,
    help="Output CSV file path.",
)
@click.option("--area-path", default="", help="ADO Area Path.")
@click.option("--iteration-path", default="", help="ADO Iteration Path.")
def export(
    report: str,
    matrix: str,
    output: str,
    area_path: str,
    iteration_path: str,
    advisor: str | None,
) -> None:
    """Run analysis and export an ADO-compatible CSV."""
    from excellence_agent.analysis import (
        HierarchyBuilder,
        ResourceMapper,
    )
    from excellence_agent.config import ADOConfig
    from excellence_agent.export.ado_csv import ADOExporter
    from excellence_agent.export.content_generator import ContentGenerator
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

    # Export
    click.echo(click.style("▶ Exporting to CSV …", fg="cyan"))
    ado_config = ADOConfig(area_path=area_path, iteration_path=iteration_path)
    content_gen = ContentGenerator()
    exporter = ADOExporter(config=ado_config, content_generator=content_gen)

    try:
        out_path = exporter.export(hierarchy, output)
    except Exception as exc:
        raise click.ClickException(f"Export failed: {exc}") from exc

    stats = hierarchy.summary_stats()
    click.echo(click.style(f"\n✔ CSV exported to {out_path}", fg="green"))
    click.echo(f"  Epics:        {stats['epics']}")
    click.echo(f"  Features:     {stats['features']}")
    click.echo(f"  User Stories: {stats['user_stories']}")
    click.echo(f"  Recommendations: {stats['recommendations']}")
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
# customers
# ---------------------------------------------------------------------------

@cli.group()
def customers() -> None:
    """Manage per-customer ADO configurations."""


@customers.command("list")
def customers_list() -> None:
    """List available customer configurations."""
    from excellence_agent.ado.customer_config import list_customer_configs

    configs = list_customer_configs()
    if not configs:
        click.echo("No customer configs found in customers/ directory.")
        click.echo("Create one from customers/example.yaml")
        return

    click.echo(click.style(f"Found {len(configs)} customer config(s):\n", fg="cyan"))
    for c in configs:
        click.echo(f"  {click.style(c['slug'], fg='green')}  —  {c['customer_name']}")


@customers.command("validate")
@click.argument("slug")
def customers_validate(slug: str) -> None:
    """Validate a customer config (loads YAML + checks PAT)."""
    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config

    try:
        cfg = load_customer_config(slug)
    except CustomerConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(click.style(f"✔ Config valid for '{slug}'", fg="green"))
    click.echo(f"  Organization: {cfg.organization}")
    click.echo(f"  Project:      {cfg.project}")
    click.echo(f"  Team:         {cfg.team or '(default)'}")
    click.echo(f"  Area path:    {cfg.area_path or '(none)'}")
    click.echo(f"  PAT:          {'*' * 8}…{cfg.pat[-4:]}")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------

@cli.group()
def sync() -> None:
    """Sync work items to Azure DevOps via MCP."""


def _sync_options(fn):
    """Common options for sync commands that need report + customer."""
    fn = click.argument("slug")(fn)
    fn = click.option(
        "--report", required=True,
        type=click.Path(exists=True, dir_okay=False),
        help="Path to the APRL v2 Excel report.",
    )(fn)
    fn = click.option(
        "--advisor", default=None,
        type=click.Path(exists=True, dir_okay=False),
        help="Optional Advisor CSV export.",
    )(fn)
    fn = click.option(
        "--matrix", default=_DEFAULT_MATRIX,
        type=click.Path(exists=True, dir_okay=False),
        show_default=True,
    )(fn)
    return fn


def _load_sync_deps(slug: str, report: str, advisor: str | None, matrix: str):
    """Load customer config, build hierarchy, create sync service."""
    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config
    from excellence_agent.ado.state_store import SyncStateStore
    from excellence_agent.ado.sync_service import AdoSyncService
    from excellence_agent.export.content_generator import ContentGenerator
    from excellence_agent.pipeline import build_hierarchy

    try:
        config = load_customer_config(slug)
    except CustomerConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(click.style(f"▶ Building hierarchy from {report} …", fg="cyan"))
    try:
        hierarchy, stats = build_hierarchy(report, matrix, advisor_path=advisor)
    except Exception as exc:
        raise click.ClickException(f"Pipeline error: {exc}") from exc

    click.echo(
        f"  {stats['epics']} Epics, {stats['features']} Features, "
        f"{stats['user_stories']} Stories, {stats['recommendations']} Recommendations"
    )

    store = SyncStateStore()
    cg = ContentGenerator()
    service = AdoSyncService(state_store=store, content_generator=cg, config=config)
    return config, hierarchy, store, service


@sync.command("plan")
@_sync_options
def sync_plan(slug: str, report: str, advisor: str | None, matrix: str) -> None:
    """Preview what would be synced (dry run)."""
    config, hierarchy, store, service = _load_sync_deps(slug, report, advisor, matrix)

    click.echo(click.style("▶ Computing sync plan …", fg="cyan"))
    plan = service.plan(hierarchy)
    s = plan.summary()

    click.echo(click.style(f"\n✔ Sync plan for '{slug}'", fg="green"))
    click.echo(f"  Create:    {s['create']}")
    click.echo(f"  Update:    {s['update']}")
    click.echo(f"  Relink:    {s['relink']}")
    click.echo(f"  Unchanged: {s['unchanged']}")
    click.echo(f"  Orphaned:  {s['orphaned']}")
    click.echo(f"  Total:     {s['total']}")

    if plan.to_create:
        click.echo(click.style("\n  Items to create:", fg="yellow"))
        for item in plan.to_create[:20]:
            click.echo(f"    + [{item.work_item_type}] {item.title}")
        if len(plan.to_create) > 20:
            click.echo(f"    … and {len(plan.to_create) - 20} more")

    if plan.to_update:
        click.echo(click.style("\n  Items to update:", fg="yellow"))
        for item in plan.to_update[:20]:
            click.echo(f"    ~ [{item.work_item_type}] {item.title}")
        if len(plan.to_update) > 20:
            click.echo(f"    … and {len(plan.to_update) - 20} more")


@sync.command("push")
@_sync_options
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def sync_push(slug: str, report: str, advisor: str | None, matrix: str, yes: bool) -> None:
    """Sync work items to Azure DevOps."""
    config, hierarchy, store, service = _load_sync_deps(slug, report, advisor, matrix)

    click.echo(click.style("▶ Computing sync plan …", fg="cyan"))
    plan = service.plan(hierarchy)
    s = plan.summary()

    actionable = s["create"] + s["update"] + s["relink"]
    if actionable == 0:
        click.echo(click.style("✔ Nothing to sync — all items up to date.", fg="green"))
        return

    click.echo(f"  Create: {s['create']}  Update: {s['update']}  Relink: {s['relink']}  Orphaned: {s['orphaned']}")

    if not yes:
        click.confirm(f"Push {actionable} items to {config.organization}/{config.project}?", abort=True)

    click.echo(click.style("▶ Pushing to ADO via MCP …", fg="cyan"))

    async def _push():
        from excellence_agent.ado.mcp_client import ADOMCPClient

        with store.customer_lock(config.slug):
            async with ADOMCPClient(config) as client:
                return await service.push(plan, client)

    start = time.time()
    result = asyncio.run(_push())

    run = result.run
    if result.success:
        click.echo(click.style(f"\n✔ Sync complete (run #{run.id})", fg="green"))
    else:
        click.echo(click.style(f"\n✘ Sync finished with errors (run #{run.id})", fg="red"))

    click.echo(f"  Created:   {run.items_created}")
    click.echo(f"  Updated:   {run.items_updated}")
    click.echo(f"  Linked:    {run.items_linked}")
    click.echo(f"  Unchanged: {run.items_unchanged}")
    click.echo(f"  Failed:    {run.items_failed}")
    click.echo(f"  Orphaned:  {run.items_orphaned}")

    if result.errors:
        click.echo(click.style("\n  Errors:", fg="red"))
        for err in result.errors:
            click.echo(f"    ✘ {err}")

    click.echo(f"\n  Elapsed: {_elapsed(start)}")


@sync.command("status")
@click.argument("slug")
def sync_status(slug: str) -> None:
    """Show sync status for a customer."""
    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config
    from excellence_agent.ado.state_store import SyncStateStore

    try:
        config = load_customer_config(slug)
    except CustomerConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    store = SyncStateStore()
    items = store.get_items_by_customer(config.slug)
    runs = store.get_runs(config.slug, limit=5)

    if not items and not runs:
        click.echo(f"No sync data for '{slug}'.")
        return

    # Status breakdown
    from collections import Counter
    status_counts = Counter(i.sync_status for i in items)
    click.echo(click.style(f"Sync status for '{slug}' ({len(items)} tracked items):", fg="cyan"))
    for st, cnt in sorted(status_counts.items()):
        color = {"created": "green", "updated": "green", "failed": "red", "orphaned": "yellow"}.get(st, "white")
        click.echo(f"  {click.style(st, fg=color)}: {cnt}")

    if runs:
        click.echo(click.style(f"\nRecent runs:", fg="cyan"))
        for r in runs:
            status_color = "green" if r.status == "completed" else "red"
            click.echo(
                f"  #{r.id}  {click.style(r.status, fg=status_color)}  "
                f"started={r.started_at[:19]}  "
                f"C:{r.items_created} U:{r.items_updated} F:{r.items_failed}"
            )


@sync.command("retry")
@_sync_options
@click.option("--run-id", type=int, default=None, help="Retry from specific run.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def sync_retry(
    slug: str, report: str, advisor: str | None, matrix: str,
    run_id: int | None, yes: bool,
) -> None:
    """Retry failed sync items."""
    config, hierarchy, store, service = _load_sync_deps(slug, report, advisor, matrix)

    failed = store.get_items_for_retry(config.slug, run_id)
    if not failed:
        click.echo(click.style("✔ No failed items to retry.", fg="green"))
        return

    click.echo(f"Found {len(failed)} failed item(s):")
    for item in failed[:10]:
        click.echo(f"  ✘ [{item.work_item_type}] {item.title}: {item.error_message}")
    if len(failed) > 10:
        click.echo(f"  … and {len(failed) - 10} more")

    if not yes:
        click.confirm(f"Retry {len(failed)} failed items?", abort=True)

    # Re-plan to get correct fields, then push only previously-failed items
    click.echo(click.style("▶ Re-planning with current hierarchy …", fg="cyan"))
    plan = service.plan(hierarchy)

    # Filter plan to only include items that were previously failed
    failed_keys = {i.stable_key for i in failed}
    from excellence_agent.ado.sync_service import SyncPlan

    retry_plan = SyncPlan(customer=plan.customer)
    for item in plan.to_create:
        if item.stable_key in failed_keys:
            retry_plan.to_create.append(item)
    for item in plan.to_update:
        if item.stable_key in failed_keys:
            retry_plan.to_update.append(item)

    actionable = len(retry_plan.to_create) + len(retry_plan.to_update)
    if actionable == 0:
        click.echo(click.style("✔ No actionable retry items found after re-plan.", fg="green"))
        return

    click.echo(click.style(f"▶ Retrying {actionable} items …", fg="cyan"))

    async def _retry():
        from excellence_agent.ado.mcp_client import ADOMCPClient

        with store.customer_lock(config.slug):
            async with ADOMCPClient(config) as client:
                return await service.push(retry_plan, client)

    start = time.time()
    result = asyncio.run(_retry())

    run = result.run
    if result.success:
        click.echo(click.style(f"\n✔ Retry complete (run #{run.id})", fg="green"))
    else:
        click.echo(click.style(f"\n✘ Retry finished with errors (run #{run.id})", fg="red"))

    click.echo(f"  Created: {run.items_created}  Updated: {run.items_updated}  Failed: {run.items_failed}")
    click.echo(f"\n  Elapsed: {_elapsed(start)}")


# ---------------------------------------------------------------------------
# apps
# ---------------------------------------------------------------------------

@cli.group()
def apps() -> None:
    """Manage the application registry (applications.yaml)."""


@apps.command("list")
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(dir_okay=False),
    help="Path to applications.yaml (default: project root).",
)
def apps_list(config_path: str | None) -> None:
    """List all registered applications."""
    from excellence_agent.applications import load_app_registry

    registry = load_app_registry(config_path)
    app_list = registry.list_apps()

    if not app_list:
        click.echo("No applications registered.")
        click.echo("Use 'ea apps add <name>' or run incremental export with --input-dir to auto-detect.")
        return

    click.echo(click.style(f"Registered applications ({len(app_list)}):\n", fg="cyan"))
    for app in app_list:
        envs = ", ".join(app.environments) if app.environments else "(none)"
        click.echo(f"  {click.style(app.name, fg='green')}  envs: {envs}")
        if app.description:
            click.echo(f"    {app.description}")


@apps.command("add")
@click.argument("name")
@click.option("--description", "-d", default="", help="Application description.")
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(dir_okay=False),
    help="Path to applications.yaml.",
)
def apps_add(name: str, description: str, config_path: str | None) -> None:
    """Add an application to the registry."""
    from excellence_agent.applications import load_app_registry

    registry = load_app_registry(config_path)
    entry = registry.add_app(name, description=description)
    registry.save()
    click.echo(click.style(f"✔ Added application: {entry.name}", fg="green"))


@apps.command("remove")
@click.argument("name")
@click.option(
    "--config", "config_path", default=None,
    type=click.Path(dir_okay=False),
    help="Path to applications.yaml.",
)
def apps_remove(name: str, config_path: str | None) -> None:
    """Remove an application from the registry."""
    from excellence_agent.applications import load_app_registry

    registry = load_app_registry(config_path)
    if registry.remove_app(name):
        registry.save()
        click.echo(click.style(f"✔ Removed application: {name}", fg="green"))
    else:
        click.echo(click.style(f"✘ Application '{name}' not found.", fg="red"))


# ---------------------------------------------------------------------------
# export-incremental
# ---------------------------------------------------------------------------

@cli.command("export-incremental")
@click.option(
    "--report",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a single APRL Expert Analysis file.",
)
@click.option(
    "--input-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Path to batch assessment output directory.",
)
@click.option(
    "--matrix",
    default=_DEFAULT_MATRIX,
    type=click.Path(exists=True, dir_okay=False),
    show_default=True,
    help="Path to resource_matrix.yaml.",
)
@click.option(
    "--customer",
    default="_default",
    show_default=True,
    help="Customer scope for the processing ledger (usually left as default).",
)
@click.option(
    "--app",
    "app_name",
    default="ChangeMe-AppName",
    show_default=True,
    help="Application name (required for single-file mode; auto-detected for directories).",
)
@click.option(
    "--reviewed-only/--all-items",
    default=True,
    show_default=True,
    help="Only process items with REVIEW STATUS = 'Reviewed'.",
)
@click.option(
    "--env-filter",
    type=click.Choice(["All", "Prod", "OtherEnvs"], case_sensitive=False),
    default="All",
    show_default=True,
    help="Filter by environment.",
)
@click.option(
    "--output",
    default="output/ado_import_incremental.csv",
    show_default=True,
    help="Output CSV file path.",
)
@click.option("--area-path", default="", help="ADO Area Path.")
@click.option("--iteration-path", default="", help="ADO Iteration Path.")
@click.option("--advisor", default=None, type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--state-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="State directory (default: .state/).",
)
def export_incremental(
    report: str | None,
    input_dir: str | None,
    matrix: str,
    customer: str,
    app_name: str | None,
    reviewed_only: bool,
    env_filter: str,
    output: str,
    area_path: str,
    iteration_path: str,
    advisor: str | None,
    state_dir: str | None,
) -> None:
    """Run incremental pipeline and export ADO-compatible CSV.

    Processes only reviewed items not already handled in previous runs.
    Creates new numbered user stories per resource type per app.

    Use --report for a single file or --input-dir for a batch directory.
    """
    if not report and not input_dir:
        raise click.ClickException("Provide either --report or --input-dir.")
    if report and input_dir:
        raise click.ClickException("Provide only one of --report or --input-dir.")

    from excellence_agent.pipeline_v2 import build_hierarchy_incremental

    start = time.time()
    report_path = input_dir or report

    click.echo(click.style("▶ Running incremental pipeline …", fg="cyan"))
    click.echo(f"  Input:         {report_path}")
    click.echo(f"  Customer:      {customer}")
    click.echo(f"  Reviewed only: {reviewed_only}")
    click.echo(f"  Env filter:    {env_filter}")
    click.echo()

    try:
        result = build_hierarchy_incremental(
            report_path=report_path,
            matrix_path=matrix,
            customer=customer,
            reviewed_only=reviewed_only,
            env_filter=env_filter,
            app_name=app_name,
            state_dir=state_dir,
            advisor_path=advisor,
        )
    except Exception as exc:
        raise click.ClickException(f"Pipeline error: {exc}") from exc

    hierarchy = result.hierarchy

    if not hierarchy.all_stories():
        click.echo(click.style("ℹ No new items to process.", fg="yellow"))
        click.echo(f"  Items skipped (already processed): {result.items_skipped_duplicate}")
        click.echo(f"\n  Elapsed: {_elapsed(start)}")
        return

    # Export to CSV
    click.echo(click.style("▶ Exporting to CSV …", fg="cyan"))
    from excellence_agent.config import ADOConfig
    from excellence_agent.export.ado_csv import ADOExporter
    from excellence_agent.export.content_generator import ContentGenerator

    ado_config = ADOConfig(area_path=area_path, iteration_path=iteration_path)
    content_gen = ContentGenerator()
    exporter = ADOExporter(config=ado_config, content_generator=content_gen)

    # Convert V2 hierarchy to V1 for export compatibility
    from excellence_agent.models import Epic, Feature, UserStory, WorkItemHierarchy

    v1_hierarchy = _convert_v2_to_v1(hierarchy)

    try:
        out_path = exporter.export(v1_hierarchy, output)
    except Exception as exc:
        raise click.ClickException(f"Export failed: {exc}") from exc

    # Summary
    stats = result.stats
    click.echo(click.style(f"\n✔ Incremental export complete → {out_path}", fg="green"))
    click.echo(f"  Apps processed:     {', '.join(result.apps_processed)}")
    click.echo(f"  New stories:        {stats.get('user_stories', 0)}")
    click.echo(f"  Items recorded:     {result.new_items_processed}")
    click.echo(f"  Items skipped:      {result.items_skipped_duplicate}")

    if result.new_apps_detected:
        click.echo(f"  New apps detected:  {', '.join(result.new_apps_detected)}")
    if result.errors:
        click.echo(click.style(f"\n  Warnings: {len(result.errors)} file(s) had errors", fg="yellow"))

    click.echo(f"\n  Elapsed: {_elapsed(start)}")


def _convert_v2_to_v1(hierarchy_v2) -> "WorkItemHierarchy":
    """Convert a V2 hierarchy to V1 format for CSV export compatibility."""
    from excellence_agent.models import Epic, Feature, UserStory, WorkItemHierarchy

    v1 = WorkItemHierarchy()
    for epic_v2 in hierarchy_v2.epics:
        epic = Epic(name=epic_v2.app_name, description=epic_v2.description)
        epic.total_resource_count = epic_v2.total_resource_count
        epic.waf_pillars = epic_v2.waf_pillars
        epic.impact_summary = epic_v2.impact_summary

        for feat_v2 in epic_v2.features:
            # Use the first resource type as a representative for the V1 Feature
            feature = Feature(
                name=feat_v2.category_name,
                resource_type=feat_v2.category_key,
            )
            feature.resource_groups = feat_v2.resource_groups
            feature.subscriptions = feat_v2.subscriptions
            feature.resource_count = feat_v2.resource_count

            for story_v2 in feat_v2.user_stories:
                story = UserStory(
                    title=story_v2.title,
                    impact=story_v2.impact,
                    category=story_v2.category,
                    source=story_v2.source,
                    waf_pillars=story_v2.waf_pillars,
                    resource_count=story_v2.resource_count,
                )
                for rec in story_v2.recommendations:
                    story.add_recommendation(rec)
                feature.add_user_story(story)

            epic.add_feature(feature)
        v1.add_epic(epic)
    return v1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
