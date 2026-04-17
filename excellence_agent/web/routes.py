"""JSON API blueprint for the ExcellenceAgent React SPA."""

from __future__ import annotations

import asyncio
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_file,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_hierarchy():
    return current_app.config.get("EA_HIERARCHY")


def _get_dedup_report():
    return current_app.config.get("EA_DEDUP_REPORT")


def _get_patterns():
    return current_app.config.get("EA_PATTERNS")


def _get_config():
    return current_app.config["EA_CONFIG"]


def _impact_counts(hierarchy):
    """Return dict of impact level → count across all user stories."""
    counts: dict[str, int] = {"High": 0, "Medium": 0, "Low": 0}
    for story in hierarchy.all_stories():
        level = story.impact if story.impact in counts else "Low"
        counts[level] += 1
    return counts


def _error(message: str, status: int = 400):
    return jsonify(success=False, error=message), status


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/upload", methods=["POST"])
def upload():
    """Accept APRL Excel file and optional Advisor CSV, run the full pipeline."""
    file = request.files.get("aprl_file")
    if not file or file.filename == "":
        return _error("No file selected.", 400)

    advisor_file = request.files.get("advisor_file")  # Optional

    config = _get_config()

    output_dir = os.path.abspath(config.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    upload_path = os.path.join(output_dir, file.filename)
    file.save(upload_path)

    advisor_path = None
    if advisor_file and advisor_file.filename:
        advisor_path = os.path.join(output_dir, advisor_file.filename)
        advisor_file.save(advisor_path)

    try:
        from excellence_agent.ingest import APRLParser
        from excellence_agent.analysis import (
            CrossReferencer,
            Deduplicator,
            HierarchyBuilder,
            PatternDetector,
            ResourceMapper,
        )

        # 1. Parse APRL
        parser = APRLParser(upload_path)
        report = parser.parse()
        df = report.impacted_resources

        # 2. Optional Advisor merge
        xref_report = None
        matrix = config.load_resource_matrix()
        if advisor_path:
            from excellence_agent.ingest import AdvisorParser
            type_mapping = matrix.get("advisor_type_mapping", {})
            advisor_report = AdvisorParser(advisor_path, type_mapping=type_mapping).parse()
            xref = CrossReferencer()
            df, xref_report = xref.merge(df, advisor_report.recommendations)

        # 3. Map resources
        mapper = ResourceMapper(matrix)
        mapped_df = mapper.map_dataframe(df)

        # 4. Build hierarchy
        descriptions = {
            cat: info.get("description", "")
            for cat, info in matrix.get("categories", {}).items()
        }
        builder = HierarchyBuilder(category_descriptions=descriptions)
        hierarchy = builder.build(mapped_df)

        # 5. Deduplicate
        dedup = Deduplicator()
        dedup_report = dedup.analyse(hierarchy)

        # 6. Detect patterns
        detector = PatternDetector()
        patterns = detector.detect(hierarchy)

        # Store results in app-level state
        current_app.config["EA_HIERARCHY"] = hierarchy
        current_app.config["EA_DEDUP_REPORT"] = dedup_report
        current_app.config["EA_PATTERNS"] = patterns
        current_app.config["EA_XREF_REPORT"] = xref_report

        stats = hierarchy.summary_stats()
        message = (
            f"Pipeline complete — {stats['epics']} Epics, "
            f"{stats['features']} Features, "
            f"{stats['user_stories']} User Stories, "
            f"{stats['tasks']} Tasks."
        )
        if xref_report:
            message += (
                f" Cross-ref: {len(xref_report.matched_resources)} matched, "
                f"{len(xref_report.advisor_only_resources)} Advisor-only."
            )

        response_data = {
            "success": True,
            "stats": stats,
            "message": message,
        }
        if xref_report:
            response_data["cross_reference"] = xref_report.to_dict()

        return jsonify(response_data)
    except Exception as exc:
        return _error(f"Pipeline error: {exc}", 500)
    finally:
        if os.path.exists(upload_path):
            os.remove(upload_path)
        if advisor_path and os.path.exists(advisor_path):
            os.remove(advisor_path)


@api_bp.route("/cross-reference", methods=["GET"])
def cross_reference():
    """Return the cross-reference report if Advisor data was provided."""
    xref = current_app.config.get("EA_XREF_REPORT")
    if xref is None:
        return jsonify({"has_data": False})
    return jsonify({"has_data": True, **xref.to_dict()})


@api_bp.route("/stats", methods=["GET"])
def stats():
    """Return summary statistics for the loaded hierarchy."""
    hierarchy = _get_hierarchy()
    if hierarchy is None:
        return jsonify(
            has_data=False,
            epics=0,
            features=0,
            user_stories=0,
            tasks=0,
            impact_counts={"High": 0, "Medium": 0, "Low": 0},
        )
    summary = hierarchy.summary_stats()
    summary["has_data"] = True
    summary["impact_counts"] = _impact_counts(hierarchy)
    return jsonify(summary)


@api_bp.route("/hierarchy", methods=["GET"])
def hierarchy():
    """Return the full work-item hierarchy as JSON."""
    h = _get_hierarchy()
    if h is None:
        return _error("No data loaded. Upload an APRL file first.", 404)
    return jsonify(h.to_dict())


@api_bp.route("/hierarchy/epics", methods=["GET"])
def hierarchy_epics():
    """Return a lighter-weight list of epics with nested features (no stories/tasks)."""
    h = _get_hierarchy()
    if h is None:
        return _error("No data loaded. Upload an APRL file first.", 404)

    epics = []
    for epic in h.epics:
        features = []
        for f in epic.features:
            features.append({
                "name": f.name,
                "resource_type": f.resource_type,
                "resource_count": f.resource_count,
                "story_count": len(f.user_stories),
                "total_tasks": f.total_tasks(),
            })
        epics.append({
            "name": epic.name,
            "description": epic.description,
            "total_resource_count": epic.total_resource_count,
            "total_stories": epic.total_stories(),
            "total_tasks": epic.total_tasks(),
            "waf_pillars": sorted(epic.waf_pillars),
            "impact_summary": dict(epic.impact_summary),
            "features": features,
        })
    return jsonify(epics)


@api_bp.route("/patterns", methods=["GET"])
def patterns():
    """Return detected patterns as a JSON list."""
    p = _get_patterns()
    if p is None:
        return _error("No data loaded. Upload an APRL file first.", 404)
    serialised = [
        pat.to_dict() if hasattr(pat, "to_dict") else pat
        for pat in p
    ]
    return jsonify(serialised)


@api_bp.route("/dedup", methods=["GET"])
def dedup():
    """Return the deduplication report as JSON."""
    report = _get_dedup_report()
    if report is None:
        return _error("No data loaded. Upload an APRL file first.", 404)
    serialised = (
        report.to_dict() if hasattr(report, "to_dict") else report
    )
    return jsonify(serialised)


@api_bp.route("/export", methods=["POST"])
def export_csv():
    """Generate a CSV export and return it as a file download."""
    h = _get_hierarchy()
    if h is None:
        return _error("No data loaded. Upload an APRL file first.", 404)

    config = _get_config()
    data = request.get_json(silent=True) or {}
    area_path = data.get("area_path", config.ado.area_path)
    iteration_path = data.get("iteration_path", config.ado.iteration_path)

    config.ado.area_path = area_path
    config.ado.iteration_path = iteration_path

    try:
        from excellence_agent.export import ContentGenerator
        from excellence_agent.export.ado_csv import ADOExporter

        output_dir = os.path.abspath(config.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "ado_export.csv")

        generator = ContentGenerator()
        exporter = ADOExporter(config.ado, generator)
        result_path = exporter.export(h, output_path)

        return send_file(
            result_path,
            mimetype="text/csv",
            as_attachment=True,
            download_name="ado_export.csv",
        )
    except Exception as exc:
        return _error(f"Export error: {exc}", 500)


# ---------------------------------------------------------------------------
# Customer config endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/customers", methods=["GET"])
def list_customers():
    """List available customer configurations."""
    from excellence_agent.ado.customer_config import list_customer_configs

    return jsonify(list_customer_configs())


@api_bp.route("/customers/<slug>", methods=["GET"])
def get_customer(slug: str):
    """Get a customer config (PAT redacted)."""
    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config

    try:
        cfg = load_customer_config(slug)
    except CustomerConfigError as exc:
        return _error(str(exc), 404)

    return jsonify({
        "slug": cfg.slug,
        "customer_name": cfg.customer_name,
        "organization": cfg.organization,
        "project": cfg.project,
        "team": cfg.team,
        "area_path": cfg.area_path,
        "iteration_path": cfg.iteration_path,
        "pat_configured": True,
        "type_mapping": {
            "epic": cfg.type_mapping.epic,
            "feature": cfg.type_mapping.feature,
            "story": cfg.type_mapping.story,
            "task": cfg.type_mapping.task,
        },
    })


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------

def _get_sync_store():
    """Lazily create/return a SyncStateStore singleton on the app."""
    store = current_app.config.get("EA_SYNC_STORE")
    if store is None:
        from excellence_agent.ado.state_store import SyncStateStore

        store = SyncStateStore()
        current_app.config["EA_SYNC_STORE"] = store
    return store


@api_bp.route("/sync/plan", methods=["POST"])
def sync_plan():
    """Compute a sync plan for a customer using the loaded hierarchy."""
    data = request.get_json(silent=True) or {}
    slug = data.get("customer")
    if not slug:
        return _error("Missing 'customer' field.", 400)

    hierarchy = _get_hierarchy()
    if hierarchy is None:
        return _error("No hierarchy loaded. Upload an APRL file first.", 404)

    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config
    from excellence_agent.ado.sync_service import AdoSyncService
    from excellence_agent.export.content_generator import ContentGenerator

    try:
        config = load_customer_config(slug)
    except CustomerConfigError as exc:
        return _error(str(exc), 404)

    store = _get_sync_store()
    cg = ContentGenerator()
    service = AdoSyncService(state_store=store, content_generator=cg, config=config)
    plan = service.plan(hierarchy)

    def _items_json(items):
        return [
            {
                "stable_key": i.stable_key,
                "work_item_type": i.work_item_type,
                "title": i.title,
                "action": i.action,
                "parent_stable_key": i.parent_stable_key,
            }
            for i in items
        ]

    return jsonify({
        "customer": slug,
        "summary": plan.summary(),
        "to_create": _items_json(plan.to_create),
        "to_update": _items_json(plan.to_update),
        "to_relink": _items_json(plan.to_relink),
        "unchanged": _items_json(plan.unchanged),
        "orphaned": _items_json(plan.orphaned),
    })


@api_bp.route("/sync/push", methods=["POST"])
def sync_push():
    """Execute sync push for a customer."""
    data = request.get_json(silent=True) or {}
    slug = data.get("customer")
    if not slug:
        return _error("Missing 'customer' field.", 400)

    hierarchy = _get_hierarchy()
    if hierarchy is None:
        return _error("No hierarchy loaded. Upload an APRL file first.", 404)

    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config
    from excellence_agent.ado.mcp_client import ADOMCPClient
    from excellence_agent.ado.sync_service import AdoSyncService
    from excellence_agent.export.content_generator import ContentGenerator
    from filelock import Timeout

    try:
        config = load_customer_config(slug)
    except CustomerConfigError as exc:
        return _error(str(exc), 404)

    store = _get_sync_store()
    cg = ContentGenerator()
    service = AdoSyncService(state_store=store, content_generator=cg, config=config)

    async def _do_push():
        plan = service.plan(hierarchy)
        async with ADOMCPClient(config) as client:
            return await service.push(plan, client)

    try:
        with store.customer_lock(config.slug):
            result = asyncio.run(_do_push())
    except Timeout:
        return _error(f"Sync already running for '{slug}'.", 409)
    except Exception as exc:
        return _error(f"Sync error: {exc}", 500)

    run = result.run
    return jsonify({
        "success": result.success,
        "run_id": run.id,
        "status": run.status,
        "items_created": run.items_created,
        "items_updated": run.items_updated,
        "items_linked": run.items_linked,
        "items_unchanged": run.items_unchanged,
        "items_failed": run.items_failed,
        "items_orphaned": run.items_orphaned,
        "errors": result.errors,
    })


@api_bp.route("/sync/status/<slug>", methods=["GET"])
def sync_status(slug: str):
    """Get sync status for a customer (latest run + item breakdown)."""
    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config

    try:
        load_customer_config(slug)
    except CustomerConfigError as exc:
        return _error(str(exc), 404)

    store = _get_sync_store()
    items = store.get_items_by_customer(slug)
    runs = store.get_runs(slug, limit=1)

    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.sync_status] = status_counts.get(item.sync_status, 0) + 1

    latest_run = None
    if runs:
        r = runs[0]
        latest_run = {
            "id": r.id,
            "status": r.status,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "items_created": r.items_created,
            "items_updated": r.items_updated,
            "items_linked": r.items_linked,
            "items_unchanged": r.items_unchanged,
            "items_failed": r.items_failed,
            "items_orphaned": r.items_orphaned,
        }

    return jsonify({
        "customer": slug,
        "total_items": len(items),
        "status_counts": status_counts,
        "latest_run": latest_run,
    })


@api_bp.route("/sync/history/<slug>", methods=["GET"])
def sync_history(slug: str):
    """Get sync run history for a customer."""
    store = _get_sync_store()
    limit = request.args.get("limit", 20, type=int)
    runs = store.get_runs(slug, limit=min(limit, 100))

    return jsonify([
        {
            "id": r.id,
            "status": r.status,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "items_created": r.items_created,
            "items_updated": r.items_updated,
            "items_linked": r.items_linked,
            "items_unchanged": r.items_unchanged,
            "items_failed": r.items_failed,
            "items_orphaned": r.items_orphaned,
        }
        for r in runs
    ])


@api_bp.route("/sync/retry", methods=["POST"])
def sync_retry():
    """Retry failed sync items for a customer."""
    data = request.get_json(silent=True) or {}
    slug = data.get("customer")
    if not slug:
        return _error("Missing 'customer' field.", 400)

    hierarchy = _get_hierarchy()
    if hierarchy is None:
        return _error("No hierarchy loaded. Upload an APRL file first.", 404)

    from excellence_agent.ado.customer_config import CustomerConfigError, load_customer_config
    from excellence_agent.ado.mcp_client import ADOMCPClient
    from excellence_agent.ado.sync_service import AdoSyncService, SyncPlan
    from excellence_agent.export.content_generator import ContentGenerator
    from filelock import Timeout

    run_id = data.get("run_id")

    try:
        config = load_customer_config(slug)
    except CustomerConfigError as exc:
        return _error(str(exc), 404)

    store = _get_sync_store()
    cg = ContentGenerator()
    service = AdoSyncService(state_store=store, content_generator=cg, config=config)

    failed = store.get_items_for_retry(slug, run_id)
    if not failed:
        return jsonify({"success": True, "message": "No failed items to retry."})

    failed_keys = {i.stable_key for i in failed}
    plan = service.plan(hierarchy)

    retry_plan = SyncPlan(customer=plan.customer)
    for item in plan.to_create:
        if item.stable_key in failed_keys:
            retry_plan.to_create.append(item)
    for item in plan.to_update:
        if item.stable_key in failed_keys:
            retry_plan.to_update.append(item)

    async def _do_retry():
        async with ADOMCPClient(config) as client:
            return await service.push(retry_plan, client)

    try:
        with store.customer_lock(config.slug):
            result = asyncio.run(_do_retry())
    except Timeout:
        return _error(f"Sync already running for '{slug}'.", 409)
    except Exception as exc:
        return _error(f"Retry error: {exc}", 500)

    run = result.run
    return jsonify({
        "success": result.success,
        "run_id": run.id,
        "status": run.status,
        "items_created": run.items_created,
        "items_updated": run.items_updated,
        "items_failed": run.items_failed,
        "errors": result.errors,
    })
