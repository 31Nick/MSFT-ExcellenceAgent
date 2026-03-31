"""JSON API blueprint for the ExcellenceAgent React SPA."""

from __future__ import annotations

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
    """Accept APRL Excel file, run the full pipeline, return JSON summary."""
    file = request.files.get("aprl_file")
    if not file or file.filename == "":
        return _error("No file selected.", 400)

    config = _get_config()

    output_dir = os.path.abspath(config.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    upload_path = os.path.join(output_dir, file.filename)
    file.save(upload_path)

    try:
        from excellence_agent.ingest import APRLParser
        from excellence_agent.analysis import (
            Deduplicator,
            HierarchyBuilder,
            PatternDetector,
            ResourceMapper,
        )

        # 1. Parse
        parser = APRLParser(upload_path)
        report = parser.parse()

        # 2. Map resources
        matrix = config.load_resource_matrix()
        mapper = ResourceMapper(matrix)
        mapped_df = mapper.map_dataframe(report.impacted_resources)

        # 3. Build hierarchy
        descriptions = {
            cat: info.get("description", "")
            for cat, info in matrix.get("categories", {}).items()
        }
        builder = HierarchyBuilder(category_descriptions=descriptions)
        hierarchy = builder.build(mapped_df)

        # 4. Deduplicate
        dedup = Deduplicator()
        dedup_report = dedup.analyse(hierarchy)

        # 5. Detect patterns
        detector = PatternDetector()
        patterns = detector.detect(hierarchy)

        # Store results in app-level state
        current_app.config["EA_HIERARCHY"] = hierarchy
        current_app.config["EA_DEDUP_REPORT"] = dedup_report
        current_app.config["EA_PATTERNS"] = patterns

        stats = hierarchy.summary_stats()
        return jsonify(
            success=True,
            stats=stats,
            message=(
                f"Pipeline complete — {stats['epics']} Epics, "
                f"{stats['features']} Features, "
                f"{stats['user_stories']} User Stories, "
                f"{stats['tasks']} Tasks."
            ),
        )
    except Exception as exc:
        return _error(f"Pipeline error: {exc}", 500)
    finally:
        if os.path.exists(upload_path):
            os.remove(upload_path)


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
