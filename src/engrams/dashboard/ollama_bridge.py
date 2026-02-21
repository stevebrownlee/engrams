"""Optional Ollama integration for conversational project exploration (Feature 5)."""

import logging
from typing import Any, Dict, List

log = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
DEFAULT_CONTEXT_LIMIT = 20


class OllamaBridge:
    """Bridge to Ollama for local LLM chat about project context.

    Requires ``httpx`` (installed via the ``dashboard`` extras group).
    All project data stays local — requests go only to localhost.
    """

    def __init__(
        self,
        db_reader: Any,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
    ):
        self.db_reader = db_reader
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.context_limit = context_limit

    # ------------------------------------------------------------------
    # Health / discovery
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if Ollama is running and accessible."""
        try:
            import httpx  # noqa: WPS433

            response = httpx.get(f"{self.ollama_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def get_available_models(self) -> List[str]:
        """List models currently pulled in Ollama."""
        try:
            import httpx  # noqa: WPS433

            response = httpx.get(f"{self.ollama_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(self, message: str) -> Dict[str, Any]:
        """Send a message with Engrams context to Ollama.

        The flow:
        1. Search Engrams for entities relevant to *message*.
        2. Build a prompt that includes those entities as context.
        3. Call Ollama's ``/api/generate`` endpoint.
        4. On failure, fall back to returning the raw search results.

        Args:
            message: Developer's question about the project.

        Returns:
            Dict with ``response`` (str), ``context_used`` (list),
            ``model`` (str) — and optionally ``fallback`` / ``error``.
        """
        # 1. Search for relevant context
        context_items = self._search_context(message)

        # 2. Build the prompt
        prompt = self._build_prompt(message, context_items)

        # 3. Send to Ollama
        try:
            import httpx  # noqa: WPS433

            response = httpx.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120.0,
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "response": data.get("response", ""),
                    "context_used": [
                        {
                            "type": c["type"],
                            "id": c.get("id"),
                            "title": c.get("title", ""),
                        }
                        for c in context_items
                    ],
                    "model": self.model,
                }
            # Non-200 → fallback
            return self._fallback_response(
                message,
                context_items,
                f"Ollama returned status {response.status_code}",
            )
        except ImportError:
            return {
                "error": "httpx not installed. Install with: pip install httpx"
            }
        except Exception as exc:
            return self._fallback_response(message, context_items, str(exc))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_context(self, query: str) -> List[Dict[str, Any]]:
        """Search Engrams for context relevant to *query*."""
        results: List[Dict[str, Any]] = []

        # Try global FTS search first
        try:
            fts_results = self.db_reader.global_search(
                query, limit=self.context_limit
            )
            results.extend(fts_results)
        except Exception:
            pass

        # If FTS didn't yield enough, pad with recent decisions
        if len(results) < self.context_limit // 2:
            try:
                decisions = self.db_reader.get_decisions(
                    limit=self.context_limit - len(results)
                )
                existing = {
                    (r.get("type"), r.get("id"))
                    for r in results
                }
                for d in decisions:
                    if ("decision", d.get("id")) not in existing:
                        results.append(
                            {
                                "type": "decision",
                                "id": d.get("id"),
                                "title": d.get("summary", ""),
                                "snippet": (d.get("rationale", "") or "")[:200],
                            }
                        )
            except Exception:
                pass

        return results[: self.context_limit]

    def _build_prompt(
        self, question: str, context_items: List[Dict[str, Any]]
    ) -> str:
        """Build a prompt with Engrams context for a small local model."""
        context_text = ""
        for item in context_items:
            item_type = item.get("type", "unknown")
            item_id = item.get("id", "?")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            context_text += f"\n[{item_type} #{item_id}] {title}"
            if snippet:
                context_text += f"\n  {snippet}"
            context_text += "\n"

        return (
            "You are a project knowledge assistant. Answer the developer's "
            "question using ONLY the following project context. If the context "
            "doesn't contain enough information to answer, say so clearly.\n\n"
            "## Project Context\n"
            f"{context_text}\n"
            "## Developer's Question\n"
            f"{question}\n\n"
            "## Instructions\n"
            "- Only use information from the Project Context above\n"
            '- Reference item IDs when citing information (e.g., "Decision #14")\n'
            "- Be concise and specific\n"
            "- If you're unsure, say so rather than guessing"
        )

    def _fallback_response(
        self,
        question: str,
        context_items: List[Dict[str, Any]],
        error: str,
    ) -> Dict[str, Any]:
        """Return raw search results as a fallback when Ollama fails."""
        return {
            "response": (
                f"I couldn't generate a summary (error: {error}), "
                "but here are the relevant items:"
            ),
            "context_used": [
                {
                    "type": c["type"],
                    "id": c.get("id"),
                    "title": c.get("title", ""),
                }
                for c in context_items
            ],
            "fallback": True,
            "error": error,
        }
