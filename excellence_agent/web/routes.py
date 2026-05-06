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


def _get_assessment_store():
    """Get or create the AssessmentStore singleton."""
    store = current_app.config.get("EA_ASSESSMENT_STORE")
    if store is None:
        from excellence_agent.ado.assessment_store import AssessmentStore
        store = AssessmentStore()
        current_app.config["EA_ASSESSMENT_STORE"] = store
    return store


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
    """Accept APRL Excel file and optional Advisor CSV, run the V2 incremental pipeline."""
    file = request.files.get("aprl_file")
    if not file or file.filename == "":
        return _error("No file selected.", 400)

    advisor_file = request.files.get("advisor_file")  # Optional

    # App name: from form field, or default placeholder
    app_name = (request.form.get("app_name") or "").strip()
    if not app_name:
        app_name = "ChangeMe-AppName"

    # Reviewed-only toggle (default: True)
    reviewed_only_raw = request.form.get("reviewed_only", "true")
    reviewed_only = reviewed_only_raw.lower() not in ("false", "0", "no")

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
        from excellence_agent.pipeline_v2 import build_hierarchy_incremental

        result = build_hierarchy_incremental(
            report_path=upload_path,
            matrix_path=config.resource_matrix_path,
            reviewed_only=reviewed_only,
            app_name=app_name,
            advisor_path=advisor_path,
        )

        hierarchy = result.hierarchy

        # Also run pattern detection on the V2 hierarchy (via V1 conversion)
        from excellence_agent.cli import _convert_v2_to_v1

        v1_hierarchy = _convert_v2_to_v1(hierarchy) if hierarchy.all_stories() else None

        # Store results in app-level state (V2 + V1 for existing endpoints)
        current_app.config["EA_HIERARCHY"] = v1_hierarchy
        current_app.config["EA_HIERARCHY_V2"] = hierarchy
        current_app.config["EA_INCREMENTAL_RESULT"] = result

        # Patterns & dedup from V1 hierarchy (if stories exist)
        if v1_hierarchy:
            from excellence_agent.analysis import Deduplicator, PatternDetector

            dedup = Deduplicator()
            dedup_report = dedup.analyse(v1_hierarchy)
            current_app.config["EA_DEDUP_REPORT"] = dedup_report

            detector = PatternDetector()
            patterns = detector.detect(v1_hierarchy)
            current_app.config["EA_PATTERNS"] = patterns
        else:
            current_app.config["EA_DEDUP_REPORT"] = None
            current_app.config["EA_PATTERNS"] = []

        # Cross-reference report (from Advisor merge within pipeline)
        current_app.config["EA_XREF_REPORT"] = None  # TODO: capture from pipeline if needed

        stats = hierarchy.summary_stats() if hierarchy.all_stories() else {
            "epics": 0, "features": 0, "user_stories": 0, "recommendations": 0
        }

        # Persist assessment to store
        assessment_store = _get_assessment_store()
        assessment_id = assessment_store.save(
            app_name=app_name,
            hierarchy_dict=hierarchy.to_dict(),
            stats=stats,
            source_filename=file.filename,
            reviewed_only=reviewed_only,
            items_processed=result.new_items_processed,
            items_skipped=result.items_skipped_duplicate,
        )
        current_app.config["EA_ACTIVE_ASSESSMENT_ID"] = assessment_id

        message = (
            f"Pipeline complete — {stats.get('epics', 0)} Epics (Apps), "
            f"{stats.get('features', 0)} Features (Categories), "
            f"{stats.get('user_stories', 0)} User Stories. "
            f"New items: {result.new_items_processed}, "
            f"Skipped (already processed): {result.items_skipped_duplicate}."
        )

        response_data = {
            "success": True,
            "stats": stats,
            "message": message,
            "app_name": app_name,
            "new_items_processed": result.new_items_processed,
            "items_skipped_duplicate": result.items_skipped_duplicate,
            "apps_processed": result.apps_processed,
        }

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
            recommendations=0,
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
    """Return a lighter-weight list of epics with nested features (no stories/recommendations)."""
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
                "total_recommendations": f.total_recommendations(),
            })
        epics.append({
            "name": epic.name,
            "description": epic.description,
            "total_resource_count": epic.total_resource_count,
            "total_stories": epic.total_stories(),
            "total_recommendations": epic.total_recommendations(),
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


# ---------------------------------------------------------------------------
# Application registry endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/apps", methods=["GET"])
def list_apps():
    """List registered applications."""
    from excellence_agent.applications import load_app_registry

    registry = load_app_registry()
    return jsonify([
        {
            "name": app.name,
            "description": app.description,
            "environments": app.environments,
            "subscriptions": app.subscriptions,
        }
        for app in registry.list_apps()
    ])


@api_bp.route("/apps", methods=["POST"])
def add_app():
    """Add an application to the registry."""
    from excellence_agent.applications import load_app_registry

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    if not name:
        return _error("Missing 'name' field.", 400)

    registry = load_app_registry()
    entry = registry.add_app(name, description=data.get("description", ""))
    registry.save()
    return jsonify({"success": True, "app": {"name": entry.name, "description": entry.description}})


@api_bp.route("/apps/<name>", methods=["DELETE"])
def remove_app(name: str):
    """Remove an application from the registry."""
    from excellence_agent.applications import load_app_registry

    registry = load_app_registry()
    if registry.remove_app(name):
        registry.save()
        return jsonify({"success": True, "removed": name})
    return _error(f"Application '{name}' not found.", 404)


# ---------------------------------------------------------------------------
# Incremental pipeline endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/incremental/run", methods=["POST"])
def incremental_run():
    """Run the incremental pipeline on an uploaded file or specified directory.

    Accepts JSON body with:
      - report_path (str): path to single Excel file
      - input_dir (str): path to batch directory (alternative to report_path)
      - customer (str, required): customer identifier
      - reviewed_only (bool, default True): filter to reviewed items only
      - env_filter (str, default "All"): "All", "Prod", or "OtherEnvs"
      - app_name (str, optional): override app name for single-file mode
    """
    from excellence_agent.pipeline_v2 import build_hierarchy_incremental

    data = request.get_json(silent=True) or {}
    customer = data.get("customer", "").strip()
    if not customer:
        return _error("Missing 'customer' field.", 400)

    report_path = data.get("report_path") or data.get("input_dir")
    if not report_path:
        return _error("Provide 'report_path' or 'input_dir'.", 400)

    config = _get_config()

    try:
        result = build_hierarchy_incremental(
            report_path=report_path,
            matrix_path=config.resource_matrix_path,
            customer=customer,
            reviewed_only=data.get("reviewed_only", True),
            env_filter=data.get("env_filter", "All"),
            app_name=data.get("app_name"),
            advisor_path=data.get("advisor_path"),
        )
    except Exception as exc:
        return _error(f"Pipeline error: {exc}", 500)

    # Store in app config for subsequent export
    current_app.config["EA_INCREMENTAL_RESULT"] = result

    return jsonify({
        "success": True,
        "apps_processed": result.apps_processed,
        "new_apps_detected": result.new_apps_detected,
        "new_items_processed": result.new_items_processed,
        "items_skipped_duplicate": result.items_skipped_duplicate,
        "stats": result.stats,
        "errors": result.errors,
    })


@api_bp.route("/incremental/export", methods=["POST"])
def incremental_export():
    """Export the last incremental pipeline result as CSV."""
    result = current_app.config.get("EA_INCREMENTAL_RESULT")
    if result is None:
        return _error("No incremental result available. Run /api/incremental/run first.", 404)

    hierarchy = result.hierarchy
    if not hierarchy.all_stories():
        return _error("No stories to export (all items were already processed).", 404)

    config = _get_config()
    data = request.get_json(silent=True) or {}
    area_path = data.get("area_path", config.ado.area_path)
    iteration_path = data.get("iteration_path", config.ado.iteration_path)

    from excellence_agent.cli import _convert_v2_to_v1
    from excellence_agent.config import ADOConfig
    from excellence_agent.export import ContentGenerator
    from excellence_agent.export.ado_csv import ADOExporter

    ado_config = ADOConfig(area_path=area_path, iteration_path=iteration_path)
    v1_hierarchy = _convert_v2_to_v1(hierarchy)
    generator = ContentGenerator()
    exporter = ADOExporter(ado_config, generator)

    output_dir = os.path.abspath(config.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "ado_incremental_export.csv")

    try:
        result_path = exporter.export(v1_hierarchy, output_path)
    except Exception as exc:
        return _error(f"Export error: {exc}", 500)

    return send_file(
        result_path,
        mimetype="text/csv",
        as_attachment=True,
        download_name="ado_incremental_export.csv",
    )


# ---------------------------------------------------------------------------
# Assessment persistence endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/assessments", methods=["GET"])
def list_assessments():
    """List all stored assessments (summaries only, no hierarchy blob)."""
    store = _get_assessment_store()
    app_filter = request.args.get("app_name")
    summaries = store.list_assessments(app_name=app_filter or None)
    return jsonify({
        "success": True,
        "assessments": [
            {
                "id": s.id,
                "app_name": s.app_name,
                "created_at": s.created_at,
                "source_filename": s.source_filename,
                "reviewed_only": s.reviewed_only,
                "stats": s.stats,
                "items_processed": s.items_processed,
                "items_skipped": s.items_skipped,
            }
            for s in summaries
        ],
        "active_id": current_app.config.get("EA_ACTIVE_ASSESSMENT_ID"),
    })


@api_bp.route("/assessments/active", methods=["GET"])
def get_active_assessment():
    """Get info about the currently active assessment."""
    active_id = current_app.config.get("EA_ACTIVE_ASSESSMENT_ID")
    if active_id is None:
        return jsonify({"success": True, "active": None})

    store = _get_assessment_store()
    summary = store.get_summary(active_id)
    if summary is None:
        return jsonify({"success": True, "active": None})

    return jsonify({
        "success": True,
        "active": {
            "id": summary.id,
            "app_name": summary.app_name,
            "created_at": summary.created_at,
            "source_filename": summary.source_filename,
            "reviewed_only": summary.reviewed_only,
            "stats": summary.stats,
            "items_processed": summary.items_processed,
            "items_skipped": summary.items_skipped,
        },
    })


@api_bp.route("/assessments/<int:assessment_id>", methods=["GET"])
def load_assessment(assessment_id: int):
    """Load an assessment by ID, making it the active assessment."""
    store = _get_assessment_store()
    hierarchy_dict = store.load_hierarchy_dict(assessment_id)
    if hierarchy_dict is None:
        return _error("Assessment not found.", 404)

    summary = store.get_summary(assessment_id)

    # Reconstruct the V2 hierarchy
    from excellence_agent.models_v2 import WorkItemHierarchyV2

    hierarchy = WorkItemHierarchyV2.from_dict(hierarchy_dict)

    # Set as active in memory
    current_app.config["EA_HIERARCHY_V2"] = hierarchy
    current_app.config["EA_ACTIVE_ASSESSMENT_ID"] = assessment_id

    # Also convert to V1 for existing endpoint compatibility
    if hierarchy.all_stories():
        from excellence_agent.cli import _convert_v2_to_v1
        from excellence_agent.analysis import Deduplicator, PatternDetector

        v1_hierarchy = _convert_v2_to_v1(hierarchy)
        current_app.config["EA_HIERARCHY"] = v1_hierarchy

        dedup = Deduplicator()
        current_app.config["EA_DEDUP_REPORT"] = dedup.analyse(v1_hierarchy)
        detector = PatternDetector()
        current_app.config["EA_PATTERNS"] = detector.detect(v1_hierarchy)
    else:
        current_app.config["EA_HIERARCHY"] = None
        current_app.config["EA_DEDUP_REPORT"] = None
        current_app.config["EA_PATTERNS"] = []

    return jsonify({
        "success": True,
        "assessment_id": assessment_id,
        "app_name": summary.app_name if summary else "",
        "stats": summary.stats if summary else {},
        "message": f"Loaded assessment #{assessment_id} for '{summary.app_name if summary else ''}'.",
    })


@api_bp.route("/assessments/<int:assessment_id>", methods=["DELETE"])
def delete_assessment(assessment_id: int):
    """Delete a stored assessment."""
    store = _get_assessment_store()
    deleted = store.delete(assessment_id)
    if not deleted:
        return _error("Assessment not found.", 404)

    # If deleted assessment was active, clear it
    if current_app.config.get("EA_ACTIVE_ASSESSMENT_ID") == assessment_id:
        current_app.config["EA_ACTIVE_ASSESSMENT_ID"] = None
        current_app.config["EA_HIERARCHY"] = None
        current_app.config["EA_HIERARCHY_V2"] = None
        current_app.config["EA_DEDUP_REPORT"] = None
        current_app.config["EA_PATTERNS"] = []

    return jsonify({"success": True, "message": f"Assessment #{assessment_id} deleted."})
