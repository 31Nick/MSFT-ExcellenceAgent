"""Flask application factory for ExcellenceAgent JSON API + React SPA."""

from __future__ import annotations

import os

from flask import Flask, send_from_directory
from flask_cors import CORS

from excellence_agent.config import Config

# React build directory lives at excellence_agent/web/static/react
_REACT_BUILD = os.path.join(os.path.dirname(__file__), "static", "react")


def create_app(config: Config | None = None) -> Flask:
    """Flask application factory.

    Serves the React SPA from ``static/react`` and registers the
    ``/api`` blueprint for all JSON endpoints.
    """
    app = Flask(
        __name__,
        static_url_path="",
        static_folder=_REACT_BUILD,
    )
    app.secret_key = "excellence-agent-dev-key"

    CORS(app)

    if config is None:
        config = Config.from_env()

    app.config["EA_CONFIG"] = config
    # Pipeline results – populated after upload
    app.config["EA_HIERARCHY"] = None
    app.config["EA_DEDUP_REPORT"] = None
    app.config["EA_PATTERNS"] = None

    from excellence_agent.web.routes import api_bp  # noqa: E402

    app.register_blueprint(api_bp)

    # Catch-all: any non-API, non-static route falls back to index.html
    # so that React Router can handle client-side navigation.
    @app.errorhandler(404)
    def fallback_to_react(_error):
        index = os.path.join(_REACT_BUILD, "index.html")
        if os.path.isfile(index):
            return send_from_directory(_REACT_BUILD, "index.html")
        return ("React build not found. Run the React build first.", 404)

    return app
