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


@api_bp.route("/export/github", methods=["POST"])
def export_github():
    """Generate a GitHub Issues export and return it as a ZIP download."""
    h = _get_hierarchy()
    if h is None:
        return _error("No data loaded. Upload an APRL file first.", 404)

    data = request.get_json(silent=True) or {}
    repo = data.get("repo", "")
    if not repo:
        return _error("Repository (owner/repo) is required.", 400)

    config = _get_config()

    try:
        import zipfile

        from excellence_agent.config import GitHubConfig
        from excellence_agent.export.github_content import GitHubContentGenerator
        from excellence_agent.export.github_export import GitHubExporter

        github_config = GitHubConfig(
            repo=repo,
            milestone=data.get("milestone", ""),
            assignee=data.get("assignee", ""),
            extra_labels=[
                l.strip()
                for l in data.get("extra_labels", "").split(",")
                if l.strip()
            ],
        )

        content_gen = GitHubContentGenerator()
        exporter = GitHubExporter(github_config, content_gen)

        output_dir = os.path.abspath(config.output_dir)
        github_dir = os.path.join(output_dir, "github")
        os.makedirs(github_dir, exist_ok=True)

        paths = exporter.export(h, github_dir)

        zip_path = os.path.join(output_dir, "github_export.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(paths["json_path"], "github_issues.json")
            zf.write(paths["markdown_path"], "github_issues.md")

        return send_file(
            zip_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name="github_export.zip",
        )
    except Exception as exc:
        return _error(f"GitHub export error: {exc}", 500)
