"""Flask dashboard application for Engrams (Feature 5).

Standalone process — reads the same ``context_portal/context.db`` that the
MCP server writes to, but in **read-only** mode.  Start with::

    engrams-dashboard --workspace /path/to/project
    engrams-dashboard --workspace /path/to/project --enable-chat --ollama-model mistral
"""

import argparse
import logging
import os
import sys

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    workspace_path: str,
    enable_chat: bool = False,
    ollama_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.2",
    chat_context_limit: int = 20,
):
    """Create and configure the Flask dashboard application.

    Args:
        workspace_path: Absolute path to the workspace root.
        enable_chat: Whether to enable the Ollama chat panel.
        ollama_url: Ollama API endpoint.
        ollama_model: Which Ollama model to use.
        chat_context_limit: Max Engrams entities per chat query.

    Returns:
        A configured Flask ``app`` instance.
    """
    try:
        from flask import Flask, jsonify, request, send_from_directory
    except ImportError:
        print(
            "Flask is required for the dashboard. "
            "Install with: pip install 'context-portal-mcp[dashboard]'"
        )
        sys.exit(1)

    from .db_reader import EngramsReader

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, static_folder=static_dir)
    reader = EngramsReader(workspace_path)

    # Optional Ollama bridge ------------------------------------------------
    ollama_bridge = None
    if enable_chat:
        from .ollama_bridge import OllamaBridge

        ollama_bridge = OllamaBridge(
            db_reader=reader,
            ollama_url=ollama_url,
            model=ollama_model,
            context_limit=chat_context_limit,
        )

    # -----------------------------------------------------------------------
    # Static file serving
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/static/<path:filename>")
    def serve_static(filename):
        return send_from_directory(app.static_folder, filename)

    # -----------------------------------------------------------------------
    # API Routes — all read-only GETs (except /api/chat which is POST)
    # -----------------------------------------------------------------------

    @app.route("/api/overview")
    def api_overview():
        try:
            stats = reader.get_overview()
            activity = reader.get_recent_activity(limit=20)
            return jsonify({"stats": stats, "recent_activity": activity})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/product-context")
    def api_product_context():
        try:
            return jsonify(reader.get_product_context())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/active-context")
    def api_active_context():
        try:
            return jsonify(reader.get_active_context())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Decisions ---------------------------------------------------------

    @app.route("/api/decisions")
    def api_decisions():
        try:
            tags = request.args.get("tags")
            search = request.args.get("q")
            scope_id = request.args.get("scope_id", type=int)
            limit = request.args.get("limit", 100, type=int)
            offset = request.args.get("offset", 0, type=int)
            tags_list = tags.split(",") if tags else None
            results = reader.get_decisions(
                tags=tags_list,
                search=search,
                scope_id=scope_id,
                limit=limit,
                offset=offset,
            )
            return jsonify(results)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/decisions/<int:decision_id>")
    def api_decision_detail(decision_id):
        try:
            result = reader.get_decision_by_id(decision_id)
            if result:
                return jsonify(result)
            return jsonify({"error": "Not found"}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Patterns ----------------------------------------------------------

    @app.route("/api/patterns")
    def api_patterns():
        try:
            limit = request.args.get("limit", 100, type=int)
            offset = request.args.get("offset", 0, type=int)
            results = reader.get_patterns(limit=limit, offset=offset)
            return jsonify(results)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/patterns/<int:pattern_id>")
    def api_pattern_detail(pattern_id):
        try:
            result = reader.get_pattern_by_id(pattern_id)
            if result:
                return jsonify(result)
            return jsonify({"error": "Not found"}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Progress ----------------------------------------------------------

    @app.route("/api/progress")
    def api_progress():
        try:
            status = request.args.get("status")
            parent_id = request.args.get("parent_id", type=int)
            limit = request.args.get("limit", 100, type=int)
            offset = request.args.get("offset", 0, type=int)
            results = reader.get_progress(
                status=status,
                parent_id=parent_id,
                limit=limit,
                offset=offset,
            )
            return jsonify(results)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Custom Data -------------------------------------------------------

    @app.route("/api/custom-data")
    def api_custom_data():
        try:
            category = request.args.get("category")
            search = request.args.get("q")
            limit = request.args.get("limit", 100, type=int)
            offset = request.args.get("offset", 0, type=int)
            results = reader.get_custom_data(
                category=category,
                search=search,
                limit=limit,
                offset=offset,
            )
            return jsonify(results)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/custom-data/<category>/<key>")
    def api_custom_data_entry(category, key):
        try:
            result = reader.get_custom_data_entry(category, key)
            if result:
                return jsonify(result)
            return jsonify({"error": "Not found"}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Graph / Search ----------------------------------------------------

    @app.route("/api/graph")
    def api_graph():
        try:
            types = request.args.get("types")
            type_filter = types.split(",") if types else None
            return jsonify(reader.get_graph_data(type_filter=type_filter))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/search")
    def api_search():
        try:
            q = request.args.get("q", "")
            limit = request.args.get("limit", 50, type=int)
            if not q:
                return jsonify([])
            return jsonify(reader.global_search(q, limit=limit))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Governance (Feature 1) --------------------------------------------

    @app.route("/api/scopes")
    def api_scopes():
        try:
            return jsonify(reader.get_scopes())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/governance")
    def api_governance():
        try:
            rules = reader.get_governance_rules()
            amendments = reader.get_scope_amendments()
            scopes = reader.get_scopes()
            return jsonify(
                {
                    "rules": rules,
                    "amendments": amendments,
                    "scopes": scopes,
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Code Bindings (Feature 2) -----------------------------------------

    @app.route("/api/bindings")
    def api_bindings():
        try:
            return jsonify(reader.get_bindings_overview())
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- Ollama Chat (optional) --------------------------------------------

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        if not ollama_bridge:
            return (
                jsonify(
                    {
                        "error": (
                            "Chat is not enabled. "
                            "Start the dashboard with the --enable-chat flag."
                        )
                    }
                ),
                400,
            )
        try:
            data = request.get_json()
            if not data or not data.get("message"):
                return jsonify({"error": "Message is required"}), 400

            if not ollama_bridge.is_available():
                return (
                    jsonify(
                        {
                            "error": (
                                "Ollama not detected. "
                                "Start Ollama to enable project chat."
                            ),
                            "help": (
                                "Install Ollama from https://ollama.ai "
                                "and run: ollama serve"
                            ),
                        }
                    ),
                    503,
                )

            result = ollama_bridge.chat(data["message"])
            return jsonify(result)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/chat/status")
    def api_chat_status():
        if not ollama_bridge:
            return jsonify({"enabled": False})
        available = ollama_bridge.is_available()
        models = ollama_bridge.get_available_models() if available else []
        return jsonify(
            {
                "enabled": True,
                "available": available,
                "model": ollama_bridge.model,
                "available_models": models,
            }
        )

    # -----------------------------------------------------------------------
    # Teardown
    # -----------------------------------------------------------------------

    @app.teardown_appcontext
    def close_reader(exception):  # noqa: ARG001
        pass  # Reader connection persists across requests for performance

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    """CLI entry point for ``engrams-dashboard``."""
    parser = argparse.ArgumentParser(description="Engrams Project Knowledge Dashboard")
    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        default=None,
        help="Path to the workspace (defaults to current directory)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8787,
        help="Port to run the dashboard on (default: 8787)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--enable-chat",
        action="store_true",
        help="Enable the Ollama chat panel",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API endpoint (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="llama3.2",
        help="Ollama model to use (default: llama3.2)",
    )
    parser.add_argument(
        "--chat-context-limit",
        type=int,
        default=20,
        help="Max Engrams entities per chat query (default: 20)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode",
    )

    args = parser.parse_args()

    workspace = args.workspace or os.getcwd()

    # Validate DB existence before starting the server
    db_path = os.path.join(workspace, "engrams", "context.db")
    if not os.path.exists(db_path):
        print(f"Error: Engrams database not found at {db_path}")
        print(f"Make sure '{workspace}' is a workspace with Engrams initialized.")
        sys.exit(1)

    if args.host != "127.0.0.1":
        print(
            "⚠️  WARNING: Binding to a non-localhost address exposes "
            "project data on the network!"
        )
        print("   Only do this on trusted networks.\n")

    print("🔍 Engrams Dashboard")
    print(f"   Workspace: {workspace}")
    print(f"   URL: http://{args.host}:{args.port}")
    if args.enable_chat:
        print(f"   Chat: Enabled (model: {args.ollama_model})")
    print()

    app = create_app(
        workspace_path=workspace,
        enable_chat=args.enable_chat,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
        chat_context_limit=args.chat_context_limit,
    )
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
