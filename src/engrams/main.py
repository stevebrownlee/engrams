# Copyright 2025 Scott McLeod (contextportal@gmail.com)
# Copyright 2025 Steve Brownlee (steve@stevebrownlee.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=too-many-lines,too-many-arguments,too-many-positional-arguments,too-many-statements,import-outside-toplevel
"""
Engrams MCP Server Main Module.
"""
import argparse
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Dict, List, Optional, Union

import uvicorn
from fastapi import FastAPI
from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

# Local imports
try:
    from .bindings import models as binding_models
    from .budgeting import models as budget_models
    from .core import exceptions  # For custom exceptions if FastMCP doesn't map them
    from .core.workspace_detector import (  # Import workspace detection
        WorkspaceDetector,
        resolve_workspace_id,
    )
    from .db import database, models  # models for tool argument types
    from .governance import models as gov_models
    from .handlers import mcp_handlers  # We will adapt these
    from .onboarding import models as onboarding_models
except ImportError:
    sys.path.insert(
        0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    )
    from src.engrams.bindings import models as binding_models
    from src.engrams.budgeting import models as budget_models
    from src.engrams.core import exceptions
    from src.engrams.core.workspace_detector import (
        WorkspaceDetector,
        resolve_workspace_id,
    )
    from src.engrams.db import database, models
    from src.engrams.governance import models as gov_models
    from src.engrams.handlers import mcp_handlers
    from src.engrams.onboarding import models as onboarding_models

log = logging.getLogger(__name__)


def setup_logging(args: argparse.Namespace):
    """Configures logging based on command-line arguments."""
    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    root_logger = logging.getLogger()
    # Clear any existing handlers to avoid duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.setLevel(getattr(logging, args.log_level.upper()))

    # Add file handler if specified and workspace_id is available
    if args.log_file and args.workspace_id:
        try:
            log_file_path = args.log_file
            if not os.path.isabs(log_file_path):
                # This is a bit of a chicken-and-egg problem. We need the config to know
                # the base path, but the config isn't fully set up yet. We can read the
                # args directly.
                if args.base_path:
                    base_path = Path(args.base_path).expanduser()
                    sanitized_workspace_id = args.workspace_id.replace(
                        "/", "_"
                    ).replace("\\", "_")
                    log_dir = base_path / sanitized_workspace_id / "logs"
                    log_file_path = log_dir / os.path.basename(args.log_file)
                else:
                    base_path = args.workspace_id
                    log_file_path = os.path.join(base_path, "engrams", log_file_path)

            log_dir = os.path.dirname(log_file_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file_path, maxBytes=10 * 1024 * 1024, backupCount=5  # 10 MB
            )
            file_handler.setFormatter(logging.Formatter(log_format))
            root_logger.addHandler(file_handler)
            log.info("File logging configured to: %s", log_file_path)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Use a temporary basic config to log this error
            logging.basicConfig()
            log.error("Failed to set up file logging to %s: %s", args.log_file, e)
    elif args.log_file:
        log.warning(
            "Log file '%s' requested, but no --workspace_id provided at startup. "
            "File logging will be deferred.",
            args.log_file,
        )

    # Only add console handler if not in stdio mode
    if args.mode != "stdio":
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(logging.Formatter(log_format))
        root_logger.addHandler(console_handler)
        log.info("Console logging configured.")


# --- Lifespan Management for FastMCP ---
@asynccontextmanager
async def engrams_lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """Manage application lifecycle for Engrams."""
    # server is required by FastMCP lifespan signature
    log.info("Engrams FastMCP server lifespan starting.")
    # Database initialization is handled by get_db_connection on first access per workspace.
    # No explicit global startup needed for DB here unless we want to pre-connect to a default.
    try:
        yield None  # Server runs
    finally:
        log.info(
            "Engrams FastMCP server lifespan shutting down. Closing all DB connections."
        )
        database.close_all_connections()


# --- FastMCP Server Instance ---
# Version from pyproject.toml would be ideal here, or define centrally
ENGRAMS_VERSION = "0.3.13"

engrams_mcp = FastMCP(name="Engrams", lifespan=engrams_lifespan)  # Pass name directly

# --- FastAPI App ---
# The FastAPI app will be the main ASGI app, and FastMCP will be mounted onto it.
# We keep our own FastAPI app instance in case we want to add other non-MCP HTTP endpoints later.
app = FastAPI(title="Engrams MCP Server Wrapper", version=ENGRAMS_VERSION)

# --- Adapt and Register Tools with FastMCP ---
# We use our Pydantic models as input_schema for robust validation.


@engrams_mcp.tool(
    name="get_product_context",
    description="Retrieves the stored high-level product context (project goals, features, architecture) as a single JSON object. Use this for the persistent 'what is this project' definition — NOT for current work focus (use get_active_context), NOT for governance-scoped merged view (use get_effective_context), NOT for token-budgeted task context (use get_relevant_context), and NOT for structured onboarding briefings (use get_project_briefing). Returns: {content: {...}, version: int, updated_at: string}. Workflow (read-before-write): Step 1 of 2 when patching — call this first to retrieve current content, then call update_product_context(patch_content={...}) with only the keys to change. Skip this step only when doing a full content replacement via update_product_context(content={...}).",
    annotations=ToolAnnotations(
        title="Get Product Context",
        readOnlyHint=True,
    ),
)
async def tool_get_product_context(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
) -> Dict[str, Any]:
    """
    Retrieves the product context for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.

    Returns:
        A dictionary containing the product context.
    """
    try:
        # Construct the Pydantic model for the handler
        pydantic_args = models.GetContextArgs(workspace_id=workspace_id)
        return mcp_handlers.handle_get_product_context(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_product_context handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_product_context: %s. Received workspace_id: %s",
            e,
            workspace_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_product_context: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="update_product_context",
    description="Overwrites or patches the persistent product context (project goals, features, architecture). Provide content for full replacement OR patch_content for partial merge (set a key to '__DELETE__' to remove it). Only one of content/patch_content may be provided. Precondition: use get_product_context first if you need to preserve existing keys. Returns: the updated context object with new version number. Workflow (read-before-write): Step 2 of 2 when patching — must call get_product_context first to get current content, then supply patch_content with only the keys to add/change/delete. When doing a full replacement, supply content directly without reading first. Common mistake: providing both content and patch_content in the same call — this raises a validation error.",
    annotations=ToolAnnotations(
        title="Update Product Context",
        destructiveHint=True,
    ),
)
async def tool_update_product_context(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    content: Annotated[
        Optional[Dict[str, Any]],
        Field(
            default=None, description="Full replacement content object. If provided, completely replaces existing content. Mutually exclusive with patch_content — provide only one."
        ),
    ] = None,
    patch_content: Annotated[
        Optional[Dict[str, Any]],
        Field(
            default=None, description="Partial update dict. Only specified keys are changed. Set a key's value to '__DELETE__' to remove that key. Mutually exclusive with content — provide only one."
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Updates the product context for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        content: Optional full content to replace the existing context.
        patch_content: Optional partial content to update the existing context.

    Returns:
        A dictionary containing the updated product context.
    """
    try:
        # Pydantic model UpdateContextArgs will be validated by FastMCP based on annotations.
        # We still need to construct it for the handler.
        # The model's own validator will check 'content' vs 'patch_content'.
        pydantic_args = models.UpdateContextArgs(
            workspace_id=workspace_id, content=content, patch_content=patch_content
        )
        return mcp_handlers.handle_update_product_context(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in update_product_context handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors from UpdateContextArgs
        log.error(
            "Validation error for update_product_context: %s. "
            "Args: workspace_id=%s, content_present=%s, patch_content_present=%s",
            e,
            workspace_id,
            content is not None,
            patch_content is not None,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for update_product_context: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for update_product_context: %s. "
            "Args: workspace_id=%s, content_present=%s, patch_content_present=%s",
            e,
            workspace_id,
            content is not None,
            patch_content is not None,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing update_product_context: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_active_context",
    description="Retrieves the session-level active context: current work focus, open issues, and recent changes. This is the 'what am I working on right now' state — mutable and frequently updated. For the persistent project definition, use get_product_context instead. For governance-scoped merged view, use get_effective_context. Returns: {content: {...}, version: int, updated_at: string}. Workflow (read-before-write): Step 1 of 2 when patching — call this first to retrieve current content, then call update_active_context(patch_content={...}) with only the keys to change. Skip this step only when doing a full content replacement via update_active_context(content={...}).",
    annotations=ToolAnnotations(
        title="Get Active Context",
        readOnlyHint=True,
    ),
)
async def tool_get_active_context(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
) -> Dict[str, Any]:
    """
    Retrieves the active context for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.

    Returns:
        A dictionary containing the active context.
    """
    try:
        pydantic_args = models.GetContextArgs(workspace_id=workspace_id)
        return mcp_handlers.handle_get_active_context(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_active_context handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_active_context: %s. Received workspace_id: %s",
            e,
            workspace_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_active_context: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="update_active_context",
    description="Overwrites or patches the session-level active context (current focus, open issues, recent changes). Provide content for full replacement OR patch_content for partial merge (set a key to '__DELETE__' to remove it). Only one of content/patch_content may be provided. Call get_active_context first if you need to preserve existing keys. Returns: the updated active context with new version number. Workflow (read-before-write): Step 2 of 2 when patching — must call get_active_context first to get current content, then supply patch_content with only the keys to add/change/delete. When doing a full replacement, supply content directly without reading first. Common mistake: providing both content and patch_content in the same call — this raises a validation error.",
    annotations=ToolAnnotations(
        title="Update Active Context",
        destructiveHint=True,
    ),
)
async def tool_update_active_context(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    content: Annotated[
        Optional[Dict[str, Any]],
        Field(
            default=None, description="Full replacement content object. If provided, completely replaces existing content. Mutually exclusive with patch_content — provide only one."
        ),
    ] = None,
    patch_content: Annotated[
        Optional[Dict[str, Any]],
        Field(
            default=None, description="Partial update dict. Only specified keys are changed. Set a key's value to '__DELETE__' to remove that key. Mutually exclusive with content — provide only one."
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Updates the active context for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        content: Optional full content to replace the existing context.
        patch_content: Optional partial content to update the existing context.

    Returns:
        A dictionary containing the updated active context.
    """
    try:
        pydantic_args = models.UpdateContextArgs(
            workspace_id=workspace_id, content=content, patch_content=patch_content
        )
        return mcp_handlers.handle_update_active_context(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in update_active_context handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors from UpdateContextArgs
        log.error(
            "Validation error for update_active_context: %s. "
            "Args: workspace_id=%s, content_present=%s, patch_content_present=%s",
            e,
            workspace_id,
            content is not None,
            patch_content is not None,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for update_active_context: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for update_active_context: %s. "
            "Args: workspace_id=%s, content_present=%s, patch_content_present=%s",
            e,
            workspace_id,
            content is not None,
            patch_content is not None,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing update_active_context: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="log_decision",
    description="Creates a new STRATEGIC decision record — architectural choices, technology selections, coding conventions, or project constraints that guide future work across all sessions. Use this ONLY for decisions that would still be relevant if a new session started on a different feature. Do NOT use for bug fixes, code modifications, refactors, or task completions — use log_progress for those. Accepts summary (required), rationale, implementation_details, and tags. Optionally assign to a governance scope via scope_id; if scope_id is provided, visibility defaults to 'scoped' and the decision will only appear in governance checks for that scope — omit scope_id to make the decision globally visible. tags must be a JSON array of strings (e.g., ['auth', 'security']), NOT a comma-separated string. Returns: {id: int, summary, rationale, tags, created_at, ...}. For logging multiple decisions at once, use batch_log_items with item_type='decision'.",
    annotations=ToolAnnotations(
        title="Log Decision",
        destructiveHint=False,
    ),
)
async def tool_log_decision(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    summary: Annotated[
        str, Field(min_length=1, description="A concise summary of the decision")
    ],
    rationale: Annotated[
        Optional[str], Field(description="The reasoning behind the decision")
    ] = None,
    implementation_details: Annotated[
        Optional[str],
        Field(description="Details about how the decision will be/was implemented"),
    ] = None,
    tags: Annotated[
        Optional[List[str]], Field(description="Optional tags for categorization")
    ] = None,
    scope_id: Annotated[
        Optional[int], Field(description="Governance scope ID this item belongs to")
    ] = None,
    visibility: Annotated[
        Optional[str],
        Field(description="Visibility level: team, individual, proposed, or workspace"),
    ] = None,
) -> Dict[str, Any]:
    """
    Logs a new decision for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        summary: A concise summary of the decision.
        rationale: Optional reasoning behind the decision.
        implementation_details: Optional implementation details.
        tags: Optional list of tags.
        scope_id: Optional governance scope ID this item belongs to.
        visibility: Optional visibility level (team, individual, proposed, workspace).

    Returns:
        A dictionary containing the logged decision.
    """
    try:
        pydantic_args = models.LogDecisionArgs(
            workspace_id=workspace_id,
            summary=summary,
            rationale=rationale,
            implementation_details=implementation_details,
            tags=tags,
            scope_id=scope_id,
            visibility=visibility,
        )
        return mcp_handlers.handle_log_decision(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in log_decision handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for log_decision: %s. Args: workspace_id=%s, summary='%s'",
            e,
            workspace_id,
            summary,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing log_decision: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_decisions",
    description="Lists decisions, filtered by tags or ordered by recency. Use when you want to browse/filter decisions by tag or retrieve the N most recent. For keyword search across decision text, use search_decisions_fts instead. For natural-language conceptual search across ALL entity types, use semantic_search_engrams. For task-relevant context within a token budget, use get_relevant_context. Returns: [{id, summary, rationale, tags, created_at, ...}].",
    annotations=ToolAnnotations(
        title="Get Decisions",
        readOnlyHint=True,
    ),
)
async def tool_get_decisions(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(description="Maximum number of decisions to return (most recent first)"),
    ] = None,
    tags_filter_include_all: Annotated[
        Optional[List[str]],
        Field(description="Filter: items must include ALL of these tags."),
    ] = None,
    tags_filter_include_any: Annotated[
        Optional[List[str]],
        Field(description="Filter: items must include AT LEAST ONE of these tags."),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves decisions for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        limit: Optional maximum number of decisions to return.
        tags_filter_include_all: Optional list of tags that must all be present.
        tags_filter_include_any: Optional list of tags where at least one must be present.

    Returns:
        A list of dictionaries containing the decisions.
    """
    try:
        _ = ctx
        # The model's own validator will check tag filter exclusivity.
        pydantic_args = models.GetDecisionsArgs(
            workspace_id=workspace_id,
            limit=int(limit) if limit is not None else None,
            tags_filter_include_all=tags_filter_include_all,
            tags_filter_include_any=tags_filter_include_any,
        )
        return mcp_handlers.handle_get_decisions(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_decisions handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors
        log.error(
            "Validation error for get_decisions: %s. "
            "Args: workspace_id=%s, limit=%s, tags_all=%s, tags_any=%s",
            e,
            workspace_id,
            limit,
            tags_filter_include_all,
            tags_filter_include_any,
        )
        raise exceptions.ContextPortalError(f"Invalid arguments for get_decisions: {e}")
    except Exception as e:
        log.error(
            "Error processing args for get_decisions: %s. "
            "Args: workspace_id=%s, limit=%s, tags_all=%s, tags_any=%s",
            e,
            workspace_id,
            limit,
            tags_filter_include_all,
            tags_filter_include_any,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_decisions: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="search_decisions_fts",
    description="Keyword search across decision text (summary, rationale, implementation_details, tags) using SQLite FTS. Use when you have specific keywords to match. For tag-based filtering without keywords, use get_decisions. For conceptual/semantic search, use semantic_search_engrams. Returns: [{id, summary, rationale, tags, ...}] ranked by FTS relevance.",
    annotations=ToolAnnotations(
        title="Search Decisions",
        readOnlyHint=True,
    ),
)
async def tool_search_decisions_fts(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    query_term: Annotated[
        str, Field(min_length=1, description="The term to search for in decisions.")
    ],
    ctx: Context,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(
            default=10, ge=1, description="Maximum number of search results to return."
        ),
    ] = 10,
) -> List[Dict[str, Any]]:
    """
    Performs a full-text search on decisions.

    Args:
        workspace_id: The identifier for the workspace.
        query_term: The term to search for.
        ctx: The MCP context.
        limit: Optional maximum number of results to return.

    Returns:
        A list of dictionaries containing the matching decisions.
    """
    try:
        _ = ctx
        pydantic_args = models.SearchDecisionsArgs(
            workspace_id=workspace_id,
            query_term=query_term,
            limit=int(limit) if limit is not None else None,
        )
        return mcp_handlers.handle_search_decisions_fts(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in search_decisions_fts handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for search_decisions_fts: %s. "
            "Args: workspace_id=%s, query_term='%s', limit=%s",
            e,
            workspace_id,
            query_term,
            limit,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing search_decisions_fts: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="log_progress",
    description="Creates a new progress/task entry with a status (TODO, IN_PROGRESS, DONE, etc.). Use this when a task begins, a sub-task is defined, OR when implementation work is completed (bug fixes, code changes, refactors, dependency updates). Implementation-level completions belong here, NOT in log_decision. To update an existing entry's status, use update_progress instead. Supports parent_id for subtask hierarchy and linked_item_type/linked_item_id to auto-link to a decision or pattern. Returns: {id: int, description, status, parent_id, created_at, ...}.",
    annotations=ToolAnnotations(
        title="Log Progress",
        destructiveHint=False,
    ),
)
async def tool_log_progress(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    status: Annotated[
        str, Field(description="Task status. Valid values: 'TODO', 'IN_PROGRESS', 'DONE', 'BLOCKED', 'CANCELLED'.")
    ],
    description: Annotated[
        str, Field(min_length=1, description="Description of the progress or task")
    ],
    ctx: Context,
    parent_id: Annotated[
        Optional[Union[int, str]],
        Field(description="ID of the parent task, if this is a subtask"),
    ] = None,
    linked_item_type: Annotated[
        Optional[str],
        Field(
            description="Optional: Type of the Engrams item this progress entry is linked to "
            "(e.g., 'decision', 'system_pattern')"
        ),
    ] = None,
    linked_item_id: Annotated[
        Optional[str],
        Field(
            description="Optional: ID/key of the Engrams item this progress entry is linked to "
            "(requires linked_item_type)"
        ),
    ] = None,
    link_relationship_type: Annotated[
        str,
        Field(
            description="Relationship type for the automatic link, defaults to 'relates_to_progress'"
        ),
    ] = "relates_to_progress",
    scope_id: Annotated[
        Optional[int], Field(description="Governance scope ID this item belongs to")
    ] = None,
    visibility: Annotated[
        Optional[str],
        Field(description="Visibility level: team, individual, proposed, or workspace"),
    ] = None,
) -> Dict[str, Any]:
    """
    Logs a progress entry for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        status: The current status of the task.
        description: A description of the progress or task.
        ctx: The MCP context.
        parent_id: Optional ID of the parent task.
        linked_item_type: Optional type of linked item.
        linked_item_id: Optional ID of linked item.
        link_relationship_type: Relationship type for the link.
        scope_id: Optional governance scope ID this item belongs to.
        visibility: Optional visibility level (team, individual, proposed, workspace).

    Returns:
        A dictionary containing the logged progress entry.
    """
    try:
        _ = ctx
        # The model's own validator will check linked_item_type vs linked_item_id.
        pydantic_args = models.LogProgressArgs(
            workspace_id=workspace_id,
            status=status,
            description=description,
            parent_id=int(parent_id) if parent_id is not None else None,
            linked_item_type=linked_item_type,
            linked_item_id=linked_item_id,
            link_relationship_type=link_relationship_type,
            scope_id=scope_id,
            visibility=visibility,
        )
        return mcp_handlers.handle_log_progress(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in log_progress handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors
        log.error(
            "Validation error for log_progress: %s. Args: workspace_id=%s, status='%s'",
            e,
            workspace_id,
            status,
        )
        raise exceptions.ContextPortalError(f"Invalid arguments for log_progress: {e}")
    except Exception as e:
        log.error(
            "Error processing args for log_progress: %s. Args: workspace_id=%s, status='%s'",
            e,
            workspace_id,
            status,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing log_progress: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_progress",
    description="Lists progress/task entries, optionally filtered by status (e.g., 'IN_PROGRESS') or parent_id (for subtasks). Returns most recent first. Use to review task statuses or find pending work. For updating a specific entry, use update_progress. Returns: [{id, description, status, parent_id, created_at, ...}].",
    annotations=ToolAnnotations(
        title="Get Progress",
        readOnlyHint=True,
    ),
)
async def tool_get_progress(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    status_filter: Annotated[
        Optional[str], Field(description="Filter entries by status")
    ] = None,
    parent_id_filter: Annotated[
        Optional[Union[int, str]], Field(description="Filter entries by parent task ID")
    ] = None,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(description="Maximum number of entries to return (most recent first)"),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves progress entries for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        status_filter: Optional filter by status.
        parent_id_filter: Optional filter by parent task ID.
        limit: Optional maximum number of entries to return.

    Returns:
        A list of dictionaries containing the progress entries.
    """
    try:
        _ = ctx
        pydantic_args = models.GetProgressArgs(
            workspace_id=workspace_id,
            status_filter=status_filter,
            parent_id_filter=(
                int(parent_id_filter) if parent_id_filter is not None else None
            ),
            limit=int(limit) if limit is not None else None,
        )
        return mcp_handlers.handle_get_progress(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_progress handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_progress: %s. "
            "Args: workspace_id=%s, status_filter='%s', parent_id_filter=%s, limit=%s",
            e,
            workspace_id,
            status_filter,
            parent_id_filter,
            limit,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_progress: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="update_progress",
    description="Modifies an existing progress entry by its ID. Use to change status (e.g., IN_PROGRESS → DONE), update description, or reassign parent_id. At least one field must be provided. Precondition: obtain progress_id from get_progress first. Returns: the updated progress entry.",
    annotations=ToolAnnotations(
        title="Update Progress",
        destructiveHint=False,
    ),
)
async def tool_update_progress(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    progress_id: Annotated[
        Union[int, str], Field(description="The ID of the progress entry to update.")
    ],
    ctx: Context,
    status: Annotated[
        Optional[str],
        Field(description="Task status. Valid values: 'TODO', 'IN_PROGRESS', 'DONE', 'BLOCKED', 'CANCELLED'."),
    ] = None,
    description: Annotated[
        Optional[str],
        Field(min_length=1, description="New description of the progress or task"),
    ] = None,
    parent_id: Annotated[
        Optional[Union[int, str]],
        Field(description="New ID of the parent task, if changing"),
    ] = None,
) -> Dict[str, Any]:
    """
    Updates an existing progress entry.

    Args:
        workspace_id: The identifier for the workspace.
        progress_id: The ID of the progress entry to update.
        ctx: The MCP context.
        status: Optional new status.
        description: Optional new description.
        parent_id: Optional new parent task ID.

    Returns:
        A dictionary containing the updated progress entry.
    """
    try:
        _ = ctx
        # The model's own validator will check at_least_one_field.
        pydantic_args = models.UpdateProgressArgs(
            workspace_id=workspace_id,
            progress_id=int(progress_id),
            status=status,
            description=description,
            parent_id=int(parent_id) if parent_id is not None else None,
        )
        return mcp_handlers.handle_update_progress(pydantic_args)
    except exceptions.ContextPortalError as e:  # Specific app errors
        log.error("Error in update_progress handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors from UpdateProgressArgs
        log.error(
            "Validation error for update_progress: %s. "
            "Args: workspace_id=%s, progress_id=%s, status='%s', "
            "description_present=%s, parent_id=%s",
            e,
            workspace_id,
            progress_id,
            status,
            description is not None,
            parent_id,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for update_progress: {e}"
        )
    except Exception as e:  # Catch-all for other unexpected errors
        log.error(
            "Unexpected error processing args for update_progress: %s. "
            "Args: workspace_id=%s, progress_id=%s",
            e,
            workspace_id,
            progress_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing update_progress: {type(e).__name__} - {e}"
        )


@engrams_mcp.tool(
    name="log_system_pattern",
    description="Creates or updates a named system/coding pattern (e.g., 'Repository Pattern', 'Error Handling Strategy'). The name field is the unique identifier — if a pattern with the same name already exists, it will be updated. Use for recording architectural patterns, conventions, or reusable approaches. Returns: {id, name, description, tags, created_at, ...}.",
    annotations=ToolAnnotations(
        title="Log System Pattern",
        destructiveHint=False,
    ),
)
async def tool_log_system_pattern(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    name: Annotated[
        str, Field(min_length=1, description="Unique name for the system pattern")
    ],
    ctx: Context,
    description: Annotated[
        Optional[str], Field(description="Description of the pattern")
    ] = None,
    tags: Annotated[
        Optional[List[str]], Field(description="Optional tags for categorization")
    ] = None,
    scope_id: Annotated[
        Optional[int], Field(description="Governance scope ID this item belongs to")
    ] = None,
    visibility: Annotated[
        Optional[str],
        Field(description="Visibility level: team, individual, proposed, or workspace"),
    ] = None,
) -> Dict[str, Any]:
    """
    Logs a system pattern for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        name: The name of the pattern.
        ctx: The MCP context.
        description: Optional description of the pattern.
        tags: Optional list of tags.
        scope_id: Optional governance scope ID this item belongs to.
        visibility: Optional visibility level (team, individual, proposed, workspace).

    Returns:
        A dictionary containing the logged system pattern.
    """
    try:
        _ = ctx
        pydantic_args = models.LogSystemPatternArgs(
            workspace_id=workspace_id,
            name=name,
            description=description,
            tags=tags,
            scope_id=scope_id,
            visibility=visibility,
        )
        return mcp_handlers.handle_log_system_pattern(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in log_system_pattern handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for log_system_pattern: %s. Args: workspace_id=%s, name='%s'",
            e,
            workspace_id,
            name,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing log_system_pattern: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_system_patterns",
    description="Lists system/coding patterns, optionally filtered by tags. Returns most recent first. Use to review established patterns or find patterns by tag. There is no FTS search for patterns — for keyword search across patterns, use semantic_search_engrams with filter_item_types=['system_pattern']. Returns: [{id, name, description, tags, created_at, ...}].",
    annotations=ToolAnnotations(
        title="Get System Patterns",
        readOnlyHint=True,
    ),
)
async def tool_get_system_patterns(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(description="Maximum number of patterns to return"),
    ] = None,
    tags_filter_include_all: Annotated[
        Optional[List[str]],
        Field(description="Filter: items must include ALL of these tags."),
    ] = None,
    tags_filter_include_any: Annotated[
        Optional[List[str]],
        Field(description="Filter: items must include AT LEAST ONE of these tags."),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves system patterns for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        limit: Optional maximum number of patterns to return.
        tags_filter_include_all: Optional list of tags that must all be present.
        tags_filter_include_any: Optional list of tags where at least one must be present.

    Returns:
        A list of dictionaries containing the system patterns.
    """
    try:
        _ = ctx
        # The model's own validator will check tag filter exclusivity.
        pydantic_args = models.GetSystemPatternsArgs(
            workspace_id=workspace_id,
            limit=int(limit) if limit is not None else None,
            tags_filter_include_all=tags_filter_include_all,
            tags_filter_include_any=tags_filter_include_any,
        )
        return mcp_handlers.handle_get_system_patterns(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_system_patterns handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors
        log.error(
            "Validation error for get_system_patterns: %s. "
            "Args: workspace_id=%s, tags_all=%s, tags_any=%s",
            e,
            workspace_id,
            tags_filter_include_all,
            tags_filter_include_any,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for get_system_patterns: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for get_system_patterns: %s. "
            "Args: workspace_id=%s, tags_all=%s, tags_any=%s",
            e,
            workspace_id,
            tags_filter_include_all,
            tags_filter_include_any,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_system_patterns: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="log_custom_data",
    description="Stores or updates a custom key-value entry organized by category. Use for any structured data not covered by decisions, progress, or patterns (e.g., glossary terms under category 'ProjectGlossary', config settings under 'critical_settings', meeting notes, technical specs). The (category, key) pair is the unique identifier — existing entries are overwritten. Value can be any JSON-serializable type. Returns: {category, key, value, created_at}.",
    annotations=ToolAnnotations(
        title="Log Custom Data",
        destructiveHint=False,
    ),
)
async def tool_log_custom_data(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    category: Annotated[
        str, Field(min_length=1, description="Category for the custom data")
    ],
    key: Annotated[
        str,
        Field(
            min_length=1, description="Key for the custom data (unique within category)"
        ),
    ],
    value: Annotated[
        Any, Field(description="The custom data value (JSON serializable)")
    ],
    ctx: Context,
    scope_id: Annotated[
        Optional[int], Field(description="Governance scope ID this item belongs to")
    ] = None,
    visibility: Annotated[
        Optional[str],
        Field(description="Visibility level: team, individual, proposed, or workspace"),
    ] = None,
) -> Dict[str, Any]:
    """
    Logs custom data for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        category: The category for the data.
        key: The key for the data.
        value: The value to store.
        ctx: The MCP context.
        scope_id: Optional governance scope ID this item belongs to.
        visibility: Optional visibility level (team, individual, proposed, workspace).

    Returns:
        A dictionary containing the logged custom data.
    """
    try:
        _ = ctx
        pydantic_args = models.LogCustomDataArgs(
            workspace_id=workspace_id,
            category=category,
            key=key,
            value=value,
            scope_id=scope_id,
            visibility=visibility,
        )
        return mcp_handlers.handle_log_custom_data(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in log_custom_data handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for log_custom_data: %s. "
            "Args: workspace_id=%s, category='%s', key='%s'",
            e,
            workspace_id,
            category,
            key,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing log_custom_data: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_custom_data",
    description="Retrieves custom data entries by exact category and/or key lookup. Provide category alone to list all entries in that category, or both category+key for a specific entry. Omit both to list all custom data. For keyword search across custom data values, use search_custom_data_value_fts. For glossary-specific search, use search_project_glossary_fts. Returns: [{category, key, value, created_at, ...}].",
    annotations=ToolAnnotations(
        title="Get Custom Data",
        readOnlyHint=True,
    ),
)
async def tool_get_custom_data(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    category: Annotated[Optional[str], Field(description="Filter by category")] = None,
    key: Annotated[
        Optional[str], Field(description="Filter by key (requires category)")
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves custom data for the specified workspace.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        category: Optional category filter.
        key: Optional key filter.

    Returns:
        A list of dictionaries containing the custom data.
    """
    try:
        _ = ctx
        pydantic_args = models.GetCustomDataArgs(
            workspace_id=workspace_id, category=category, key=key
        )
        return mcp_handlers.handle_get_custom_data(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_custom_data handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_custom_data: %s. "
            "Args: workspace_id=%s, category='%s', key='%s'",
            e,
            workspace_id,
            category,
            key,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_custom_data: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="export_engrams_to_markdown",
    description="Exports ALL Engrams data (decisions, patterns, progress, custom data, contexts, links) to a directory of markdown files for backup, sharing, or version control. Output goes to output_path (default: ./engrams_export/). The exported format is compatible with import_markdown_to_engrams for round-tripping. Returns: {exported_path, file_count, entity_counts}.",
    annotations=ToolAnnotations(
        title="Export to Markdown",
        destructiveHint=False,
    ),
)
async def tool_export_engrams_to_markdown(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    output_path: Annotated[
        Optional[str],
        Field(
            description="Optional output directory path relative to workspace_id. "
            "Defaults to './engrams_export/' if not provided."
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Exports Engrams data to markdown files.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        output_path: Optional output directory path.

    Returns:
        A dictionary confirming the export.
    """
    try:
        _ = ctx
        pydantic_args = models.ExportEngramsToMarkdownArgs(
            workspace_id=workspace_id, output_path=output_path
        )
        return mcp_handlers.handle_export_engrams_to_markdown(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in export_engrams_to_markdown handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for export_engrams_to_markdown: %s. "
            "Args: workspace_id=%s, output_path='%s'",
            e,
            workspace_id,
            output_path,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing export_engrams_to_markdown: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="import_markdown_to_engrams",
    description="Imports Engrams data from a directory of markdown files previously created by export_engrams_to_markdown. Reads from input_path (default: ./engrams_export/). WARNING: may overwrite existing data if IDs conflict. Use for restoring backups or migrating between workspaces. Precondition: files must follow the export format. Returns: {imported_path, entity_counts, errors}.",
    annotations=ToolAnnotations(
        title="Import from Markdown",
        destructiveHint=True,
    ),
)
async def tool_import_markdown_to_engrams(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    input_path: Annotated[
        Optional[str],
        Field(
            description="Optional input directory path relative to workspace_id "
            "containing markdown files. "
            "Defaults to './engrams_export/' if not provided."
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Imports data from markdown files into Engrams.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        input_path: Optional input directory path.

    Returns:
        A dictionary confirming the import.
    """
    try:
        _ = ctx
        pydantic_args = models.ImportMarkdownToEngramsArgs(
            workspace_id=workspace_id, input_path=input_path
        )
        return mcp_handlers.handle_import_markdown_to_engrams(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in import_markdown_to_engrams handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for import_markdown_to_engrams: %s. "
            "Args: workspace_id=%s, input_path='%s'",
            e,
            workspace_id,
            input_path,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing import_markdown_to_engrams: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="link_engrams_items",
    description="Creates a directional relationship link between two Engrams items (e.g., a decision 'implements' a pattern, a progress entry 'tracks' a decision). Builds the project knowledge graph. Common relationship_types: 'implements', 'related_to', 'tracks', 'blocks', 'clarifies', 'depends_on', 'derived_from'. Item types: 'decision', 'system_pattern', 'progress_entry', 'custom_data'. Common mistakes: (1) source_item_id and target_item_id must be the integer ID as a string (e.g., '5', not 5) for decision/system_pattern/progress_entry — for custom_data items, use the string key (e.g., 'MyFeatureSpec'), not a numeric ID; (2) do not invert source and target — the relationship reads 'source VERB target' (e.g., source decision 'implements' target pattern). NOT for browsing relationships — use get_linked_items instead. Returns: {link_id, source_item_type, source_item_id, target_item_type, target_item_id, relationship_type}.",
    annotations=ToolAnnotations(
        title="Link Items",
        destructiveHint=False,
    ),
)
async def tool_link_engrams_items(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    source_item_type: Annotated[str, Field(description="Item type for the source. Valid values: 'decision', 'system_pattern', 'progress_entry', 'custom_data'.")],
    source_item_id: Annotated[str, Field(description="ID or key of the source item")],
    target_item_type: Annotated[str, Field(description="Item type for the target. Valid values: 'decision', 'system_pattern', 'progress_entry', 'custom_data'.")],
    target_item_id: Annotated[str, Field(description="ID or key of the target item")],
    relationship_type: Annotated[str, Field(description="The type of relationship. Common values: 'implements', 'related_to', 'tracks', 'blocks', 'clarifies', 'depends_on', 'derived_from'.")],
    ctx: Context,
    description: Annotated[
        Optional[str], Field(description="Optional description for the link")
    ] = None,
) -> Dict[str, Any]:
    """
    Creates a link between two Engrams items.

    Args:
        workspace_id: The identifier for the workspace.
        source_item_type: Type of the source item.
        source_item_id: ID of the source item.
        target_item_type: Type of the target item.
        target_item_id: ID of the target item.
        relationship_type: Nature of the link.
        ctx: The MCP context.
        description: Optional description for the link.

    Returns:
        A dictionary containing the created link.
    """
    try:
        _ = ctx
        pydantic_args = models.LinkEngramsItemsArgs(
            workspace_id=workspace_id,
            source_item_type=source_item_type,
            source_item_id=str(source_item_id),  # Ensure string as per model
            target_item_type=target_item_type,
            target_item_id=str(target_item_id),  # Ensure string as per model
            relationship_type=relationship_type,
            description=description,
        )
        return mcp_handlers.handle_link_engrams_items(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in link_engrams_items handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for link_engrams_items: %s. "
            "Args: workspace_id=%s, source_type='%s', source_id='%s'",
            e,
            workspace_id,
            source_item_type,
            source_item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing link_engrams_items: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_linked_items",
    description="Retrieves all knowledge graph links for a specific item (both outgoing and incoming). Use to explore relationships around a decision, pattern, progress entry, or custom data item. Optionally filter by relationship_type or linked_item_type. Returns: [{link_id, source_item_type, source_item_id, target_item_type, target_item_id, relationship_type, description, ...}]. For creating new links, use link_engrams_items.",
    annotations=ToolAnnotations(
        title="Get Linked Items",
        readOnlyHint=True,
    ),
)
async def tool_get_linked_items(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str, Field(description="Type of the item to find links for (e.g., 'decision')")
    ],
    item_id: Annotated[
        str, Field(description="ID or key of the item to find links for")
    ],
    ctx: Context,
    relationship_type_filter: Annotated[
        Optional[str], Field(description="Optional: Filter by relationship type")
    ] = None,
    linked_item_type_filter: Annotated[
        Optional[str],
        Field(description="Optional: Filter by the type of the linked items"),
    ] = None,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(description="Maximum number of links to return"),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves linked items for a specific item.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: Type of the item.
        item_id: ID of the item.
        ctx: The MCP context.
        relationship_type_filter: Optional filter by relationship type.
        linked_item_type_filter: Optional filter by linked item type.
        limit: Optional maximum number of links to return.

    Returns:
        A list of dictionaries containing the linked items.
    """
    try:
        _ = ctx
        pydantic_args = models.GetLinkedItemsArgs(
            workspace_id=workspace_id,
            item_type=item_type,
            item_id=str(item_id),  # Ensure string as per model
            relationship_type_filter=relationship_type_filter,
            linked_item_type_filter=linked_item_type_filter,
            limit=int(limit) if limit is not None else None,
        )
        return mcp_handlers.handle_get_linked_items(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_linked_items handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_linked_items: %s. "
            "Args: workspace_id=%s, item_type='%s', item_id='%s'",
            e,
            workspace_id,
            item_type,
            item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_linked_items: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="search_custom_data_value_fts",
    description="Keyword search across ALL custom data entries (values, categories, and keys) using SQLite FTS. Optionally narrow results to a single category with category_filter. Use when you have specific keywords to find in custom data. For exact category+key lookup without search, use get_custom_data. For glossary-only search, use search_project_glossary_fts. For conceptual search across all entity types, use semantic_search_engrams. Returns: [{category, key, value, ...}] ranked by FTS relevance.",
    annotations=ToolAnnotations(
        title="Search Custom Data",
        readOnlyHint=True,
    ),
)
async def tool_search_custom_data_value_fts(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    query_term: Annotated[
        str,
        Field(
            min_length=1,
            description="The term to search for in custom data (category, key, or value).",
        ),
    ],
    ctx: Context,
    category_filter: Annotated[
        Optional[str],
        Field(description="Optional: Filter results to this category after FTS."),
    ] = None,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(
            default=10, ge=1, description="Maximum number of search results to return."
        ),
    ] = 10,
) -> List[Dict[str, Any]]:
    """
    Performs a full-text search on custom data values.

    Args:
        workspace_id: The identifier for the workspace.
        query_term: The term to search for.
        ctx: The MCP context.
        category_filter: Optional category filter.
        limit: Optional maximum number of results to return.

    Returns:
        A list of dictionaries containing the matching custom data.
    """
    try:
        _ = ctx
        pydantic_args = models.SearchCustomDataValueArgs(
            workspace_id=workspace_id,
            query_term=query_term,
            category_filter=category_filter,
            limit=int(limit) if limit is not None else None,
        )
        return mcp_handlers.handle_search_custom_data_value_fts(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in search_custom_data_value_fts handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for search_custom_data_value_fts: %s. "
            "Args: workspace_id=%s, query_term='%s', category_filter='%s', limit=%s",
            e,
            workspace_id,
            query_term,
            category_filter,
            limit,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing search_custom_data_value_fts: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="batch_log_items",
    description="Logs multiple items of the SAME type in a single call, reducing round-trips. Supported item_types: 'decision', 'progress_entry', 'system_pattern', 'custom_data'. Each item in the items list is a dict with the same fields as the corresponding single-item log tool (e.g., log_decision args) — do NOT include workspace_id in the individual item dicts; it is provided once at the top level. All items in the batch must be the same type — do NOT mix decisions and patterns in one call; make separate batch_log_items calls for different types. NOT for updating existing items — use update_progress or update_product_context for edits. Returns: {logged_count, item_type, results: [...]}.",
    annotations=ToolAnnotations(
        title="Batch Log Items",
        destructiveHint=False,
    ),
)
async def tool_batch_log_items(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(
            description="Type of items to batch-log. Valid values: 'decision', 'progress_entry', 'system_pattern', 'custom_data'."
        ),
    ],
    items: Annotated[
        List[Dict[str, Any]],
        Field(
            description="A list of dictionaries, each representing the arguments for a single item log."
        ),
    ],
    ctx: Context,
) -> Dict[str, Any]:
    """
    Logs multiple items in a batch.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: The type of items to log.
        items: A list of item dictionaries.
        ctx: The MCP context.

    Returns:
        A dictionary confirming the batch log.
    """
    try:
        _ = ctx
        # Basic validation for items being a list is handled by Pydantic/FastMCP.
        # More complex validation (e.g. structure of dicts within items) happens in the handler.
        pydantic_args = models.BatchLogItemsArgs(
            workspace_id=workspace_id, item_type=item_type, items=items
        )
        return mcp_handlers.handle_batch_log_items(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in batch_log_items handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for batch_log_items: %s. "
            "Args: workspace_id=%s, item_type='%s', num_items=%s",
            e,
            workspace_id,
            item_type,
            len(items) if isinstance(items, list) else "N/A",
        )
        raise exceptions.ContextPortalError(
            f"Server error processing batch_log_items: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_item_history",
    description="Retrieves version history for Product Context or Active Context ONLY (not decisions, progress, or other entity types). Use to review past versions, audit when changes were made, or recover a previous state. Filter by timestamp range or specific version number. item_type must be 'product_context' or 'active_context'. Returns: [{version, content, updated_at, ...}] ordered most recent first.",
    annotations=ToolAnnotations(
        title="Get Item History",
        readOnlyHint=True,
    ),
)
async def tool_get_item_history(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(description="Type of context to retrieve history for. Valid values: 'product_context', 'active_context'."),
    ],
    ctx: Context,
    limit: Annotated[
        Optional[Union[int, str]],
        Field(
            description="Maximum number of history entries to return (most recent first)"
        ),
    ] = None,
    before_timestamp: Annotated[
        Optional[datetime], Field(description="Return entries before this timestamp")
    ] = None,
    after_timestamp: Annotated[
        Optional[datetime], Field(description="Return entries after this timestamp")
    ] = None,
    version: Annotated[
        Optional[Union[int, str]], Field(description="Return a specific version")
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves the history of a context item.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: The type of item (product_context or active_context).
        ctx: The MCP context.
        limit: Optional maximum number of entries.
        before_timestamp: Optional timestamp filter.
        after_timestamp: Optional timestamp filter.
        version: Optional version number.

    Returns:
        A list of dictionaries containing the history entries.
    """
    try:
        _ = ctx
        # The model's own validator will check item_type.
        pydantic_args = models.GetItemHistoryArgs(
            workspace_id=workspace_id,
            item_type=item_type,
            limit=int(limit) if limit is not None else None,
            before_timestamp=before_timestamp,
            after_timestamp=after_timestamp,
            version=int(version) if version is not None else None,
        )
        return mcp_handlers.handle_get_item_history(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_item_history handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors
        log.error(
            "Validation error for get_item_history: %s. Args: workspace_id=%s, item_type='%s'",
            e,
            workspace_id,
            item_type,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for get_item_history: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for get_item_history: %s. Args: workspace_id=%s, item_type='%s'",
            e,
            workspace_id,
            item_type,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_item_history: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="delete_item",
    description="Permanently deletes an Engrams item. For decisions, patterns, and progress entries: provide item_type and item_id (numeric). For custom data: provide item_type='custom_data' with category and key. Destructive and irreversible. Returns: {status: 'deleted', item_type, ...}.",
    annotations=ToolAnnotations(
        title="Delete Item",
        destructiveHint=True,
    ),
)
async def tool_delete_item(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(description="Type of item to delete. Valid values: 'decision', 'system_pattern', 'progress_entry', 'custom_data'."),
    ],
    item_id: Annotated[
        Optional[Union[int, str]],
        Field(description="Numeric ID of the item (required for decision, system_pattern, progress_entry)"),
    ] = None,
    category: Annotated[
        Optional[str],
        Field(description="Category of custom data (required when item_type='custom_data')"),
    ] = None,
    key: Annotated[
        Optional[str],
        Field(description="Key of custom data (required when item_type='custom_data')"),
    ] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """
    Permanently deletes an Engrams item by type and identifier.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: Type of item ('decision', 'system_pattern', 'progress_entry', 'custom_data').
        item_id: Numeric ID (required for ID-based types).
        category: Category (required for custom_data).
        key: Key (required for custom_data).
        ctx: The MCP context.

    Returns:
        A dictionary confirming the deletion.
    """
    try:
        if ctx is not None:
            _ = ctx

        # Validate parameters based on item_type
        if item_type == "decision":
            if item_id is None:
                raise exceptions.ToolArgumentError(
                    "item_id is required when item_type='decision'"
                )
            pydantic_args = models.DeleteDecisionByIdArgs(
                workspace_id=workspace_id, decision_id=int(item_id)
            )
            return mcp_handlers.handle_delete_decision_by_id(pydantic_args)

        elif item_type == "system_pattern":
            if item_id is None:
                raise exceptions.ToolArgumentError(
                    "item_id is required when item_type='system_pattern'"
                )
            pydantic_args = models.DeleteSystemPatternByIdArgs(
                workspace_id=workspace_id, pattern_id=int(item_id)
            )
            return mcp_handlers.handle_delete_system_pattern_by_id(pydantic_args)

        elif item_type == "progress_entry":
            if item_id is None:
                raise exceptions.ToolArgumentError(
                    "item_id is required when item_type='progress_entry'"
                )
            pydantic_args = models.DeleteProgressByIdArgs(
                workspace_id=workspace_id, progress_id=int(item_id)
            )
            return mcp_handlers.handle_delete_progress_by_id(pydantic_args)

        elif item_type == "custom_data":
            if category is None or key is None:
                raise exceptions.ToolArgumentError(
                    "Both category and key are required when item_type='custom_data'"
                )
            pydantic_args = models.DeleteCustomDataArgs(
                workspace_id=workspace_id, category=category, key=key
            )
            return mcp_handlers.handle_delete_custom_data(pydantic_args)

        else:
            raise exceptions.ToolArgumentError(
                f"Unknown item_type '{item_type}'. Valid types: decision, system_pattern, progress_entry, custom_data"
            )

    except exceptions.ContextPortalError as e:
        log.error("Error in delete_item handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for delete_item: %s. "
            "Args: workspace_id=%s, item_type='%s', item_id=%s, category='%s', key='%s'",
            e,
            workspace_id,
            item_type,
            item_id,
            category,
            key,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing delete_item: {type(e).__name__}"
        )



@engrams_mcp.tool(
    name="get_recent_activity_summary",
    description="Returns a digest of recently created or updated items across all entity types, ideal for session start catch-up. Specify a time window via hours_ago (e.g., 24) OR since_timestamp (not both). Limits results per entity type via limit_per_type (default 5). Use at session start to understand what changed since last interaction. NOT for searching — use search tools for that. Returns: {decisions: [...], progress: [...], patterns: [...], custom_data: [...], summary_period, ...}.",
    annotations=ToolAnnotations(
        title="Get Activity Summary",
        readOnlyHint=True,
    ),
)
async def tool_get_recent_activity_summary(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    ctx: Context,
    hours_ago: Annotated[
        Optional[Union[int, str]],
        Field(
            description="Look back this many hours for recent activity. "
            "Mutually exclusive with 'since_timestamp'."
        ),
    ] = None,
    since_timestamp: Annotated[
        Optional[datetime],
        Field(
            description="Look back for activity since this specific timestamp. "
            "Mutually exclusive with 'hours_ago'."
        ),
    ] = None,
    limit_per_type: Annotated[
        Optional[Union[int, str]],
        Field(
            default=5,
            description="Maximum number of recent items to show per activity type "
            "(e.g., 5 most recent decisions).",
        ),
    ] = 5,
) -> Dict[str, Any]:
    """
    Retrieves a summary of recent activity.

    Args:
        workspace_id: The identifier for the workspace.
        ctx: The MCP context.
        hours_ago: Optional hours to look back.
        since_timestamp: Optional timestamp to look back from.
        limit_per_type: Optional limit per item type.

    Returns:
        A dictionary containing the activity summary.
    """
    try:
        _ = ctx
        # The model's own validator will check hours_ago vs since_timestamp.
        pydantic_args = models.GetRecentActivitySummaryArgs(
            workspace_id=workspace_id,
            hours_ago=int(hours_ago) if hours_ago is not None else None,
            since_timestamp=since_timestamp,
            limit_per_type=int(limit_per_type) if limit_per_type is not None else None,
        )
        return mcp_handlers.handle_get_recent_activity_summary(pydantic_args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_recent_activity_summary handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors
        log.error(
            "Validation error for get_recent_activity_summary: %s. "
            "Args: workspace_id=%s, hours_ago=%s, since_timestamp=%s",
            e,
            workspace_id,
            hours_ago,
            since_timestamp,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for get_recent_activity_summary: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for get_recent_activity_summary: %s. "
            "Args: workspace_id=%s, hours_ago=%s, since_timestamp=%s",
            e,
            workspace_id,
            hours_ago,
            since_timestamp,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_recent_activity_summary: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="semantic_search_engrams",
    description="Natural-language conceptual search across ALL Engrams entity types (decisions, patterns, progress, custom data) using vector embeddings. Use when you have a conceptual query that keyword search would miss (e.g., 'how do we handle authentication failures' instead of exact keywords). Requires sentence-transformers to be installed. Optionally filter by item types, tags, or custom data categories. For exact keyword matching on decisions, use search_decisions_fts. For exact keyword matching on custom data, use search_custom_data_value_fts. Returns: [{item_type, item_id, content_summary, similarity_score, ...}] ranked by semantic similarity.",
    annotations=ToolAnnotations(
        title="Semantic Search",
        readOnlyHint=True,
    ),
)
async def tool_semantic_search_engrams(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    query_text: Annotated[
        str,
        Field(
            min_length=1,
            description="The natural language query text for semantic search.",
        ),
    ],
    ctx: Context,
    top_k: Annotated[
        Union[int, str],
        Field(default=5, le=25, description="Number of top results to return."),
    ] = 5,
    filter_item_types: Annotated[
        Optional[List[str]],
        Field(
            description="Optional list of item types to filter by "
            "(e.g., ['decision', 'custom_data']). "
            "Valid types: 'decision', 'system_pattern', 'custom_data', 'progress_entry'."
        ),
    ] = None,
    filter_tags_include_any: Annotated[
        Optional[List[str]],
        Field(
            description="Optional list of tags; results will include items matching any of these tags."
        ),
    ] = None,
    filter_tags_include_all: Annotated[
        Optional[List[str]],
        Field(
            description="Optional list of tags; "
            "results will include only items matching all of these tags."
        ),
    ] = None,
    filter_custom_data_categories: Annotated[
        Optional[List[str]],
        Field(
            description="Optional list of categories to filter by "
            "if 'custom_data' is in filter_item_types."
        ),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Performs a semantic search across Engrams data.

    Args:
        workspace_id: The identifier for the workspace.
        query_text: The query text.
        ctx: The MCP context.
        top_k: Number of results to return.
        filter_item_types: Optional list of item types to filter by.
        filter_tags_include_any: Optional list of tags (any).
        filter_tags_include_all: Optional list of tags (all).
        filter_custom_data_categories: Optional list of custom data categories.

    Returns:
        A list of dictionaries containing the search results.
    """
    try:
        _ = ctx
        # The model's own validators will check tag filters and custom_data_category_filter.
        pydantic_args = models.SemanticSearchEngramsArgs(
            workspace_id=workspace_id,
            query_text=query_text,
            top_k=int(top_k),
            filter_item_types=filter_item_types,
            filter_tags_include_any=filter_tags_include_any,
            filter_tags_include_all=filter_tags_include_all,
            filter_custom_data_categories=filter_custom_data_categories,
        )
        # Ensure the handler is awaited if it's async
        return await mcp_handlers.handle_semantic_search_engrams(pydantic_args)
    except exceptions.ContextPortalError as e:  # Specific app errors
        log.error("Error in semantic_search_engrams handler: %s", e)
        raise
    except ValueError as e:  # Catch Pydantic validation errors
        log.error(
            "Validation error for semantic_search_engrams: %s. "
            "Args: workspace_id=%s, query_text='%s'",
            e,
            workspace_id,
            query_text,
        )
        raise exceptions.ContextPortalError(
            f"Invalid arguments for semantic_search_engrams: {e}"
        )
    except Exception as e:  # Catch-all for other unexpected errors
        log.error(
            "Unexpected error processing args for semantic_search_engrams: %s. "
            "Args: workspace_id=%s, query_text='%s'",
            e,
            workspace_id,
            query_text,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing semantic_search_engrams: {type(e).__name__} - {e}"
        )



# --- Governance Tools (Feature 1) ---


@engrams_mcp.tool(
    name="create_scope",
    description="Creates a new governance scope (container for rules and items). Two types: 'team' (shared rules all members must follow) or 'individual' (personal scope under a team, set parent_scope_id). This is the first step in setting up governance — you must create scopes before logging rules. Returns: {id, scope_type, scope_name, created_by, parent_scope_id, created_at}. To list existing scopes, use get_scopes. Workflow (governance setup): Step 1 of 4 — create_scope (this tool) → log_governance_rule(scope_id=<returned id>) → log items with scope_id parameter → check_compliance(item_type, item_id). Common mistake: attempting to call log_governance_rule before a scope exists — scope_id must reference a real scope created by this tool or returned by get_scopes.",
    annotations=ToolAnnotations(
        title="Create Scope",
        destructiveHint=False,
    ),
)
async def tool_create_scope(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    scope_type: Annotated[
        str, Field(description="Type of governance scope. Valid values: 'team' (shared rules) or 'individual' (personal scope under a team, set parent_scope_id).")
    ],
    scope_name: Annotated[
        str, Field(min_length=1, description="Human-readable name for the scope")
    ],
    created_by: Annotated[
        str,
        Field(min_length=1, description="Who is creating this scope (e.g., username)"),
    ],
    parent_scope_id: Annotated[
        Optional[int],
        Field(description="Parent scope ID (for individual scopes under a team scope)"),
    ] = None,
) -> Dict[str, Any]:
    """
    Creates a new governance scope (team or individual).

    Args:
        workspace_id: The identifier for the workspace.
        scope_type: 'team' or 'individual'.
        scope_name: Human-readable name for the scope.
        created_by: Who is creating this scope.
        parent_scope_id: Optional parent scope ID for hierarchy.

    Returns:
        A dictionary containing the created scope.
    """
    try:
        args = gov_models.CreateScopeArgs(
            workspace_id=workspace_id,
            scope_type=scope_type,
            scope_name=scope_name,
            created_by=created_by,
            parent_scope_id=parent_scope_id,
        )
        return mcp_handlers.handle_create_scope(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in create_scope handler: %s", e)
        raise
    except ValueError as e:
        log.error("Validation error for create_scope: %s", e)
        raise exceptions.ContextPortalError(f"Invalid arguments for create_scope: {e}")
    except Exception as e:
        log.error(
            "Error processing args for create_scope: %s. Args: workspace_id=%s, scope_type='%s'",
            e,
            workspace_id,
            scope_type,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing create_scope: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_scopes",
    description="Lists all governance scopes in the workspace, optionally filtered by scope_type ('team' or 'individual'). Use to discover existing scopes before creating rules, checking compliance, or assigning items to scopes. Returns: [{id, scope_type, scope_name, parent_scope_id, created_by, ...}]. To create a new scope, use create_scope.",
    annotations=ToolAnnotations(
        title="Get Scopes",
        readOnlyHint=True,
    ),
)
async def tool_get_scopes(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    scope_type: Annotated[
        Optional[str],
        Field(description="Optional filter by scope type: 'team' or 'individual'"),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Lists all governance scopes in the workspace.

    Args:
        workspace_id: The identifier for the workspace.
        scope_type: Optional filter by scope type.

    Returns:
        A list of scope dictionaries.
    """
    try:
        args = gov_models.GetScopesArgs(
            workspace_id=workspace_id,
            scope_type=scope_type,
        )
        return mcp_handlers.handle_get_scopes(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_scopes handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_scopes: %s. Args: workspace_id=%s",
            e,
            workspace_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_scopes: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="log_governance_rule",
    description="Creates an enforcement rule within a governance scope. Rules define what is blocked or warned for specific entity types. rule_type controls enforcement: 'hard_block' (prevents action), 'soft_warn' (allows with warning), 'allow_with_flag' (allows but flags for review). rule_definition supports: blocked_tags, required_tags, blocked_keywords, required_keywords. Precondition: the scope_id must exist (use create_scope or get_scopes first). Returns: {id, scope_id, rule_type, entity_type, rule_definition, ...}. To check an item against rules, use check_compliance. Workflow (governance setup): Step 2 of 4 — create_scope → log_governance_rule (this tool, use scope_id from step 1) → log items with scope_id parameter → check_compliance(item_type, item_id). Common mistake: supplying a scope_id that does not exist — query get_scopes first to confirm valid IDs. Note: check_compliance returns vacuous 'allow' if no rules are logged for the scope, so rules must be created before compliance checks are meaningful.",
    annotations=ToolAnnotations(
        title="Log Governance Rule",
        destructiveHint=False,
    ),
)
async def tool_log_governance_rule(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    scope_id: Annotated[
        int,
        Field(
            description="The scope this rule belongs to (references context_scopes.id)"
        ),
    ],
    rule_type: Annotated[
        str,
        Field(
            description="Enforcement behavior. Valid values: 'hard_block' (prevents action), 'soft_warn' (allows with warning), 'allow_with_flag' (allows but flags for review)."
        ),
    ],
    entity_type: Annotated[
        str,
        Field(
            description="Which entity type this rule governs (e.g., 'decision', 'system_pattern')"
        ),
    ],
    rule_definition: Annotated[
        Dict[str, Any],
        Field(
            description="Structured rule definition as JSON object. "
            "Supports keys: blocked_tags, required_tags, blocked_keywords, required_keywords."
        ),
    ],
    description: Annotated[
        Optional[str],
        Field(description="Human-readable description of what this rule enforces"),
    ] = None,
) -> Dict[str, Any]:
    """
    Logs a new governance rule for a scope.

    Args:
        workspace_id: The identifier for the workspace.
        scope_id: The scope this rule belongs to.
        rule_type: The enforcement type.
        entity_type: Which entity type this rule governs.
        rule_definition: Structured rule definition.
        description: Optional human-readable description.

    Returns:
        A dictionary containing the created rule.
    """
    try:
        args = gov_models.LogGovernanceRuleArgs(
            workspace_id=workspace_id,
            scope_id=scope_id,
            rule_type=rule_type,
            entity_type=entity_type,
            rule_definition=rule_definition,
            description=description,
        )
        return mcp_handlers.handle_log_governance_rule(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in log_governance_rule handler: %s", e)
        raise
    except ValueError as e:
        log.error("Validation error for log_governance_rule: %s", e)
        raise exceptions.ContextPortalError(
            f"Invalid arguments for log_governance_rule: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for log_governance_rule: %s. Args: workspace_id=%s, scope_id=%s",
            e,
            workspace_id,
            scope_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing log_governance_rule: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_governance_rules",
    description="Lists the active governance rules for a specific scope, optionally filtered by entity_type (e.g., 'decision', 'system_pattern'). Use to review what rules exist BEFORE logging items, or to understand why a compliance check flagged something. Requires scope_id. To check a specific item against these rules, use check_compliance instead. Returns: [{id, scope_id, rule_type, entity_type, rule_definition, description, ...}]. Workflow (governance inspection): Use between steps 2 and 3 of the governance chain — after log_governance_rule and before logging items — to verify rules are correctly configured. Also use after check_compliance raises a conflict to understand which rule was violated: the conflict response includes rule_id which maps to id in this tool's output.",
    annotations=ToolAnnotations(
        title="Get Governance Rules",
        readOnlyHint=True,
    ),
)
async def tool_get_governance_rules(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    scope_id: Annotated[
        int, Field(description="Scope to get rules for (references context_scopes.id)")
    ],
    entity_type: Annotated[
        Optional[str],
        Field(
            description="Optional filter by entity type (e.g., 'decision', 'system_pattern')"
        ),
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves governance rules for a scope.

    Args:
        workspace_id: The identifier for the workspace.
        scope_id: The scope to get rules for.
        entity_type: Optional entity type filter.

    Returns:
        A list of governance rule dictionaries.
    """
    try:
        args = gov_models.GetGovernanceRulesArgs(
            workspace_id=workspace_id,
            scope_id=scope_id,
            entity_type=entity_type,
        )
        return mcp_handlers.handle_get_governance_rules(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_governance_rules handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_governance_rules: %s. Args: workspace_id=%s, scope_id=%s",
            e,
            workspace_id,
            scope_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_governance_rules: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="check_compliance",
    description="Evaluates a specific existing item (by item_type and item_id) against all applicable governance rules. Use AFTER an item is logged to verify compliance, or as a pre-check during the governance gate. Returns conflict details: {has_conflict: bool, conflicts: [...], action: 'block'|'warn'|'allow', warnings: [...]}. For listing rules without checking a specific item, use get_governance_rules. For checking rules BEFORE creating an item, simulate by reviewing get_governance_rules for the relevant scope. Workflow (governance setup): Step 4 of 4 — create_scope → log_governance_rule → log item with scope_id (e.g., log_decision, log_system_pattern) → check_compliance (this tool, use item_type and item_id from the log step). Preconditions: (1) a scope must exist, (2) at least one rule must be logged in that scope via log_governance_rule, (3) the item must already be logged and assigned to the scope. Common mistake: calling check_compliance on an item not assigned to a scope with rules — returns vacuous 'allow' with has_conflict=false, which does not mean the item is compliant.",
    annotations=ToolAnnotations(
        title="Check Compliance",
        readOnlyHint=True,
    ),
)
async def tool_check_compliance(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(description="Entity type to check (e.g., 'decision', 'system_pattern')"),
    ],
    item_id: Annotated[int, Field(description="Entity ID to check compliance for")],
) -> Dict[str, Any]:
    """
    Checks an item against team governance rules.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: The entity type to check.
        item_id: The entity ID to check.

    Returns:
        A dictionary containing compliance check results.
    """
    try:
        args = gov_models.CheckComplianceArgs(
            workspace_id=workspace_id,
            item_type=item_type,
            item_id=item_id,
        )
        return mcp_handlers.handle_check_compliance(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in check_compliance handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for check_compliance: %s. Args: workspace_id=%s, item_type='%s', item_id=%s",
            e,
            workspace_id,
            item_type,
            item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing check_compliance: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_scope_amendments",
    description="Lists proposed changes (amendments) to governance scopes, optionally filtered by status ('proposed', 'under_review', 'accepted', 'rejected') or scope_id. Amendments are change requests that require review before taking effect. To accept or reject an amendment, use review_amendment. Returns: [{id, scope_id, status, proposed_changes, proposed_by, ...}].",
    annotations=ToolAnnotations(
        title="Get Scope Amendments",
        readOnlyHint=True,
    ),
)
async def tool_get_scope_amendments(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    status: Annotated[
        Optional[str],
        Field(
            description="Optional filter by amendment status: 'proposed', 'under_review', 'accepted', 'rejected'"
        ),
    ] = None,
    scope_id: Annotated[
        Optional[int], Field(description="Optional filter by scope ID")
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Lists scope amendments with optional filters.

    Args:
        workspace_id: The identifier for the workspace.
        status: Optional status filter.
        scope_id: Optional scope filter.

    Returns:
        A list of scope amendment dictionaries.
    """
    try:
        args = gov_models.GetScopeAmendmentsArgs(
            workspace_id=workspace_id,
            status=status,
            scope_id=scope_id,
        )
        return mcp_handlers.handle_get_scope_amendments(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_scope_amendments handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_scope_amendments: %s. Args: workspace_id=%s",
            e,
            workspace_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_scope_amendments: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="review_amendment",
    description="Accepts or rejects a proposed governance scope amendment. Precondition: the amendment must exist and be in a reviewable state — use get_scope_amendments to find amendment IDs. status must be 'accepted' or 'rejected'. reviewed_by identifies the reviewer. Returns: {amendment_id, status, reviewed_by, reviewed_at}.",
    annotations=ToolAnnotations(
        title="Review Amendment",
        destructiveHint=True,
    ),
)
async def tool_review_amendment(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    amendment_id: Annotated[int, Field(description="ID of the amendment to review")],
    status: Annotated[
        str, Field(description="Review decision: 'accepted' or 'rejected'")
    ],
    reviewed_by: Annotated[
        str,
        Field(
            min_length=1, description="Who is reviewing this amendment (e.g., username)"
        ),
    ],
) -> Dict[str, Any]:
    """
    Reviews a scope amendment (accept or reject).

    Args:
        workspace_id: The identifier for the workspace.
        amendment_id: The amendment ID to review.
        status: 'accepted' or 'rejected'.
        reviewed_by: Who is reviewing.

    Returns:
        A dictionary confirming the review result.
    """
    try:
        args = gov_models.ReviewAmendmentArgs(
            workspace_id=workspace_id,
            amendment_id=amendment_id,
            status=status,
            reviewed_by=reviewed_by,
        )
        return mcp_handlers.handle_review_amendment(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in review_amendment handler: %s", e)
        raise
    except ValueError as e:
        log.error("Validation error for review_amendment: %s", e)
        raise exceptions.ContextPortalError(
            f"Invalid arguments for review_amendment: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for review_amendment: %s. Args: workspace_id=%s, amendment_id=%s",
            e,
            workspace_id,
            amendment_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing review_amendment: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_effective_context",
    description="Retrieves the merged governance view for a specific individual scope: team-level items (taking precedence) layered with individual-scope items. Use when a developer needs to see all applicable decisions, patterns, and rules combining their team's and their own scopes. Requires an individual scope_id (not team). For raw product/active context without governance, use get_product_context or get_active_context. Returns: {team_items: {...}, individual_items: {...}, merged_decisions: [...], merged_patterns: [...], ...}.",
    annotations=ToolAnnotations(
        title="Get Effective Context",
        readOnlyHint=True,
    ),
)
async def tool_get_effective_context(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    scope_id: Annotated[
        int, Field(description="Individual scope ID to get effective context for")
    ],
) -> Dict[str, Any]:
    """
    Gets merged team + individual context for a developer scope.

    Args:
        workspace_id: The identifier for the workspace.
        scope_id: The individual scope ID.

    Returns:
        A dictionary containing merged effective context with team items first.
    """
    try:
        args = gov_models.GetEffectiveContextArgs(
            workspace_id=workspace_id,
            scope_id=scope_id,
        )
        return mcp_handlers.handle_get_effective_context(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_effective_context handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_effective_context: %s. Args: workspace_id=%s, scope_id=%s",
            e,
            workspace_id,
            scope_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_effective_context: {type(e).__name__}"
        )


# --- Code Bindings Tools (Feature 2) ---


@engrams_mcp.tool(
    name="bind_code_to_item",
    description="Creates a code binding linking an Engrams entity to file paths via glob patterns. Valid item_type values: 'decision', 'system_pattern', 'progress_entry', 'custom_data'. binding_type defines the relationship: 'implements' (code implements this decision), 'governed_by' (code is governed by this rule), 'tests' (test files for this item), 'documents' (docs for this item), 'configures' (config files for this item). file_pattern supports glob syntax: 'src/auth/service.py' (exact single file), 'src/auth/**/*.py' (recursive directory match), 'tests/test_auth*.py' (prefix wildcard) — do NOT use bare directory names without a wildcard, they will not match any files. Optional symbol_pattern narrows to specific functions or class names within matched files (e.g., 'AuthService', 'login_*'). NOT for listing bindings (use get_bindings_for_item) or retrieving context by file (use get_context_for_files). For AI-suggested bindings, use suggest_bindings first. Workflow (code binding): Step 1 of 3 — bind_code_to_item (this tool) → verify_bindings(item_type, item_id) → get_bindings_for_item(item_type, item_id). Returns: {id, item_type, item_id, file_pattern, binding_type, symbol_pattern, created_at}.",
    annotations=ToolAnnotations(
        title="Bind Code to Item",
        destructiveHint=False,
    ),
)
async def tool_bind_code_to_item(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(description="Engrams entity type (e.g., 'decision', 'system_pattern')"),
    ],
    item_id: Annotated[int, Field(description="ID of the Engrams entity")],
    file_pattern: Annotated[
        str,
        Field(
            min_length=1, description="Glob or path pattern (e.g., 'src/auth/**/*.py')"
        ),
    ],
    binding_type: Annotated[
        str,
        Field(
            description="Relationship between the entity and the code. Valid values: 'implements' (code implements this entity), 'governed_by' (code is governed by this rule), 'tests' (test files), 'documents' (doc files), 'configures' (config files)."
        ),
    ],
    symbol_pattern: Annotated[
        Optional[str],
        Field(
            description="Optional function/class name pattern (e.g., 'validate_token')"
        ),
    ] = None,
    confidence: Annotated[
        str,
        Field(
            description="Confidence level: 'manual', 'agent_suggested', 'auto_detected'"
        ),
    ] = "manual",
) -> Dict[str, Any]:
    """
    Creates a code binding between a Engrams entity and file patterns.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: Engrams entity type.
        item_id: Entity ID.
        file_pattern: Glob or path pattern.
        binding_type: Nature of the binding.
        symbol_pattern: Optional symbol pattern.
        confidence: Confidence level.

    Returns:
        A dictionary containing the created binding.
    """
    try:
        args = binding_models.BindCodeToItemArgs(
            workspace_id=workspace_id,
            item_type=item_type,
            item_id=item_id,
            file_pattern=file_pattern,
            symbol_pattern=symbol_pattern,
            binding_type=binding_type,
            confidence=confidence,
        )
        return mcp_handlers.handle_bind_code_to_item(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in bind_code_to_item handler: %s", e)
        raise
    except ValueError as e:
        log.error("Validation error for bind_code_to_item: %s", e)
        raise exceptions.ContextPortalError(
            f"Invalid arguments for bind_code_to_item: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for bind_code_to_item: %s. Args: workspace_id=%s, item_type='%s', item_id=%s",
            e,
            workspace_id,
            item_type,
            item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing bind_code_to_item: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_bindings_for_item",
    description="Lists all code bindings attached to a specific Engrams entity (by item_type and item_id). Use to see which files are associated with a decision or pattern. This is entity→files lookup. For the reverse direction (files→entities), use get_context_for_files. Returns: [{id, file_pattern, symbol_pattern, binding_type, confidence, last_verified, ...}]. Workflow (code binding query): Step 3a of 3 (entity→files direction) — call after bind_code_to_item and verify_bindings have been run. If last_verified is null or stale, call verify_bindings first to confirm globs still match real files.",
    annotations=ToolAnnotations(
        title="Get Bindings for Item",
        readOnlyHint=True,
    ),
)
async def tool_get_bindings_for_item(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(description="Engrams entity type (e.g., 'decision', 'system_pattern')"),
    ],
    item_id: Annotated[int, Field(description="ID of the Engrams entity")],
) -> List[Dict[str, Any]]:
    """
    Gets all code bindings for a Engrams entity.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: Engrams entity type.
        item_id: Entity ID.

    Returns:
        A list of binding dictionaries.
    """
    try:
        args = binding_models.GetBindingsForItemArgs(
            workspace_id=workspace_id,
            item_type=item_type,
            item_id=item_id,
        )
        return mcp_handlers.handle_get_bindings_for_item(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_bindings_for_item handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_bindings_for_item: %s. Args: workspace_id=%s, item_type='%s', item_id=%s",
            e,
            workspace_id,
            item_type,
            item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_bindings_for_item: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="get_context_for_files",
    description="Given file paths being edited, returns ALL Engrams entities (decisions, patterns, etc.) bound to those paths. This is the primary files→entities lookup for codebase-context bridging — call this when an agent opens or modifies files to discover relevant project knowledge. For the reverse direction (entity→files), use get_bindings_for_item. Optionally filter by binding_type. Returns: {entities_by_type: {decisions: [...], patterns: [...]}, total_count: int}. Workflow (code binding query): Step 3b of 3 (files→entities direction) — provide exact file paths (not globs) as file_paths; the tool matches these against stored glob patterns. Call after bind_code_to_item has been run to create bindings. If results are empty, bindings may not exist yet (use suggest_bindings to propose them) or the glob patterns may not match (use verify_bindings to diagnose).",
    annotations=ToolAnnotations(
        title="Get Context for Files",
        readOnlyHint=True,
    ),
)
async def tool_get_context_for_files(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    file_paths: Annotated[
        List[str],
        Field(
            description="List of file paths being edited (relative to workspace root)"
        ),
    ],
    binding_type_filter: Annotated[
        Optional[str],
        Field(
            description="Optional filter by binding type (e.g., 'implements', 'governed_by')"
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Given file paths, returns all Engrams entities bound to those paths.

    Args:
        workspace_id: The identifier for the workspace.
        file_paths: List of file paths being edited.
        binding_type_filter: Optional binding type filter.

    Returns:
        A dictionary with entities grouped by type, plus total count.
    """
    try:
        args = binding_models.GetContextForFilesArgs(
            workspace_id=workspace_id,
            file_paths=file_paths,
            binding_type_filter=binding_type_filter,
        )
        return mcp_handlers.handle_get_context_for_files(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_context_for_files handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for get_context_for_files: %s. Args: workspace_id=%s, file_paths=%s",
            e,
            workspace_id,
            file_paths,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_context_for_files: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="verify_bindings",
    description="Validates code bindings against the actual filesystem — checks which file_pattern globs still match real files. Omit item_type and item_id to verify ALL bindings workspace-wide. Updates last_verified timestamps. Use periodically or after major refactors. For finding bindings that are already known to be stale, use get_stale_bindings instead (cheaper, no filesystem scan). Returns: {verified_count, valid: [...], broken: [...], ...}. Workflow (code binding): Step 2 of 3 — bind_code_to_item → verify_bindings (this tool, confirm the glob matches real files) → get_context_for_files or get_bindings_for_item. Common mistake: calling verify_bindings before any bindings exist — it returns verified_count=0 with empty valid/broken arrays, not an error. Use get_bindings_for_item first to confirm bindings exist. Broken bindings (files deleted or moved) should be updated via bind_code_to_item with the corrected file_pattern.",
    annotations=ToolAnnotations(
        title="Verify Bindings",
        readOnlyHint=False,
    ),
)
async def tool_verify_bindings(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    mode: Annotated[
        str,
        Field(description="Check mode. 'full': scans filesystem to verify bindings match real files (slower). 'staleness': lists bindings not verified recently or that failed last check (faster, no filesystem scan)."),
    ] = "full",
    days_stale: Annotated[
        int,
        Field(description="Only used when mode='staleness': days since last verification to consider stale"),
    ] = 30,
    item_type: Annotated[
        Optional[str],
        Field(
            description="Optional: filter verification to bindings for this entity type"
        ),
    ] = None,
    item_id: Annotated[
        Optional[int],
        Field(
            description="Optional: filter verification to bindings for this entity ID"
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Verifies code binding health with two modes: full filesystem check or staleness check.

    Args:
        workspace_id: The identifier for the workspace.
        mode: 'full' for filesystem verification or 'staleness' for timestamp-only check.
        days_stale: Days threshold for staleness (only used when mode='staleness').
        item_type: Optional entity type filter.
        item_id: Optional entity ID filter.

    Returns:
        A dictionary with verification results for each binding.
    """
    try:
        if mode == "full":
            args = binding_models.VerifyBindingsArgs(
                workspace_id=workspace_id,
                item_type=item_type,
                item_id=item_id,
            )
            return mcp_handlers.handle_verify_bindings(args)
        elif mode == "staleness":
            args = binding_models.GetStaleBindingsArgs(
                workspace_id=workspace_id,
                days_stale=days_stale,
            )
            stale_bindings = mcp_handlers.handle_get_stale_bindings(args)
            return {
                "status": "success",
                "stale": stale_bindings,
                "stale_count": len(stale_bindings),
            }
        else:
            raise exceptions.ToolArgumentError(
                f"Invalid mode '{mode}'. Must be 'full' or 'staleness'."
            )
    except exceptions.ContextPortalError as e:
        log.error("Error in verify_bindings handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for verify_bindings: %s. Args: workspace_id=%s, mode='%s', item_type='%s', item_id=%s",
            e,
            workspace_id,
            mode,
            item_type,
            item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing verify_bindings: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="suggest_bindings",
    description="Analyzes an Engrams entity's text content (summary, rationale, description) and suggests likely file glob patterns based on references to paths, modules, or technologies. Use before bind_code_to_item to get AI-assisted binding suggestions. Does NOT create bindings — review suggestions and call bind_code_to_item to create them. Returns: {suggestions: [{file_pattern, confidence, reason}, ...]}.",
    annotations=ToolAnnotations(
        title="Suggest Bindings",
        readOnlyHint=True,
    ),
)
async def tool_suggest_bindings(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    item_type: Annotated[
        str,
        Field(description="Engrams entity type (e.g., 'decision', 'system_pattern')"),
    ],
    item_id: Annotated[int, Field(description="ID of the Engrams entity")],
) -> Dict[str, Any]:
    """
    Suggests file patterns for a Engrams entity based on its text content.

    Args:
        workspace_id: The identifier for the workspace.
        item_type: Engrams entity type.
        item_id: Entity ID.

    Returns:
        A dictionary containing suggested file patterns.
    """
    try:
        args = binding_models.SuggestBindingsArgs(
            workspace_id=workspace_id,
            item_type=item_type,
            item_id=item_id,
        )
        return mcp_handlers.handle_suggest_bindings(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in suggest_bindings handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for suggest_bindings: %s. Args: workspace_id=%s, item_type='%s', item_id=%s",
            e,
            workspace_id,
            item_type,
            item_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing suggest_bindings: {type(e).__name__}"
        )


@engrams_mcp.tool(
    name="unbind_code_from_item",
    description="Permanently removes a code binding by its numeric binding_id. Destructive and irreversible. Precondition: obtain binding_id from get_bindings_for_item or verify_bindings. Returns: {status: 'deleted', binding_id: int}.",
    annotations=ToolAnnotations(
        title="Unbind Code from Item",
        destructiveHint=True,
    ),
)
async def tool_unbind_code_from_item(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    binding_id: Annotated[int, Field(description="ID of the code binding to remove")],
) -> Dict[str, Any]:
    """
    Removes a code binding by its ID.

    Args:
        workspace_id: The identifier for the workspace.
        binding_id: ID of the binding to remove.

    Returns:
        A dictionary confirming the deletion.
    """
    try:
        args = binding_models.UnbindCodeFromItemArgs(
            workspace_id=workspace_id,
            binding_id=binding_id,
        )
        return mcp_handlers.handle_unbind_code_from_item(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in unbind_code_from_item handler: %s", e)
        raise
    except Exception as e:
        log.error(
            "Error processing args for unbind_code_from_item: %s. Args: workspace_id=%s, binding_id=%s",
            e,
            workspace_id,
            binding_id,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing unbind_code_from_item: {type(e).__name__}"
        )


# --- Context Budgeting Tools (Feature 3) ---


@engrams_mcp.tool(
    name="get_relevant_context",
    description="Returns the OPTIMAL subset of ALL Engrams entities (decisions, patterns, progress, custom data) that fit within a token budget, scored by 7 relevance factors. This is the highest-level retrieval tool — use it when you need task-relevant context but don't know exactly which entities matter. Requires task_description and token_budget. profile selects a scoring preset — valid values: 'default' (balanced), 'code_review' (weights patterns/bindings), 'decision_making' (weights decisions/governance), 'onboarding' (weights product context and patterns). Set dry_run=True to preview entity counts and token estimates without retrieving content (replaces estimate_context_size). NOT for browsing/filtering specific entity types (use get_decisions, get_progress, etc.). NOT for keyword search (use FTS tools). NOT for a human-readable briefing (use get_project_briefing). Returns when dry_run=False: {selected_entities: [...], scores: [...], tokens_used: int, tokens_budget: int, excluded: [...]}. Returns when dry_run=True: {entity_counts: {type: count}, format_estimates: {...}, recommended_budgets: {task_type: tokens}} — NOTE: the return shape is completely different; do not expect selected_entities in dry_run mode.",
    annotations=ToolAnnotations(
        title="Get Relevant Context",
        readOnlyHint=True,
    ),
)
async def tool_get_relevant_context(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    task_description: Annotated[
        str,
        Field(
            min_length=1,
            description="Description of the current task for relevance scoring",
        ),
    ],
    token_budget: Annotated[
        Union[int, str],
        Field(description="Maximum token budget for the returned context"),
    ],
    dry_run: Annotated[
        bool,
        Field(description="If True, return entity counts and token estimates only (replaces estimate_context_size)"),
    ] = False,
    profile: Annotated[
        Optional[str],
        Field(
            description="Scoring profile: 'task_focused', 'architectural_overview', "
            "'onboarding', 'review', or 'custom'"
        ),
    ] = "task_focused",
    file_paths: Annotated[
        Optional[List[str]],
        Field(description="Files being edited, for code proximity scoring"),
    ] = None,
    scope_id: Annotated[
        Optional[Union[int, str]],
        Field(description="Optional scope ID for filtering (from governance feature)"),
    ] = None,
    format: Annotated[
        Optional[str],
        Field(description="Entity format: 'compact', 'standard', or 'verbose'"),
    ] = "standard",
) -> Dict[str, Any]:
    """
    Get budget-optimized relevant context for a task.

    Scores all Engrams entities across 7 factors (semantic similarity, recency,
    reference frequency, lifecycle status, scope priority, code proximity, and
    explicit priority) and selects the optimal subset within the token budget.

    Args:
        workspace_id: The identifier for the workspace.
        task_description: Description of the current task.
        token_budget: Maximum token budget.
        dry_run: If True, return size estimates only without entity content.
        profile: Scoring profile name.
        file_paths: Optional files being edited.
        scope_id: Optional scope ID for filtering.
        format: Entity output format.

    Returns:
        A dictionary with selected entities, scores, token usage, and excluded items.
        Or when dry_run=True: entity counts, token estimates, and recommended budgets.
    """
    try:
        if dry_run:
            # Route to estimate handler when dry_run=True
            args = budget_models.EstimateContextSizeArgs(
                workspace_id=workspace_id,
                task_description=task_description,
                profile=profile,
            )
            return mcp_handlers.handle_estimate_context_size(args)
        else:
            # Normal retrieval path
            args = budget_models.GetRelevantContextArgs(
                workspace_id=workspace_id,
                task_description=task_description,
                token_budget=int(token_budget),
                profile=profile,
                file_paths=file_paths,
                scope_id=int(scope_id) if scope_id is not None else None,
                format=format,
            )
            return mcp_handlers.handle_get_relevant_context(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_relevant_context handler: %s", e)
        raise
    except ValueError as e:
        log.error("Validation error for get_relevant_context: %s", e)
        raise exceptions.ContextPortalError(
            f"Invalid arguments for get_relevant_context: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for get_relevant_context: %s. "
            "Args: workspace_id=%s, task_description='%s', token_budget=%s, dry_run=%s",
            e,
            workspace_id,
            task_description,
            token_budget,
            dry_run,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_relevant_context: {type(e).__name__}"
        )



@engrams_mcp.tool(
    name="manage_budget_config",
    description="Reads or updates scoring weight configuration for get_relevant_context. Omit weights to read current config; provide a JSON string of weight overrides to update. Valid factors: semantic_similarity, recency, reference_frequency, lifecycle_status, scope_priority, code_proximity, explicit_priority. Each 0.0-1.0. Returns: {weights: {...}, source: 'custom'|'default'}.",
    annotations=ToolAnnotations(
        title="Manage Budget Config",
        destructiveHint=False,
    ),
)
async def tool_manage_budget_config(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    weights: Annotated[
        Optional[str],
        Field(
            description="JSON string of weight overrides to update (e.g., '{\"semantic_similarity\": 0.4, \"recency\": 0.2}'). "
            "Omit this parameter to read the current configuration instead. Each value must be between 0.0 and 1.0."
        ),
    ] = None,
) -> Dict[str, Any]:
    """
    Reads or updates scoring weights configuration for context budgeting.

    Args:
        workspace_id: The identifier for the workspace.
        weights: Optional JSON string of weight overrides. Omit to read current config.

    Returns:
        A dictionary with current/updated weights and their source (custom or default).
    """
    import json as _json

    try:
        if weights is None:
            # Read mode
            args = budget_models.GetContextBudgetConfigArgs(
                workspace_id=workspace_id,
            )
            return mcp_handlers.handle_get_context_budget_config(args)
        else:
            # Update mode
            parsed_weights = _json.loads(weights)
            if not isinstance(parsed_weights, dict):
                raise ValueError("weights must be a JSON object (dictionary)")
            args = budget_models.UpdateContextBudgetConfigArgs(
                workspace_id=workspace_id,
                weights=parsed_weights,
            )
            return mcp_handlers.handle_update_context_budget_config(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in manage_budget_config handler: %s", e)
        raise
    except (ValueError, _json.JSONDecodeError) as e:
        log.error("Validation error for manage_budget_config: %s", e)
        raise exceptions.ContextPortalError(
            f"Invalid arguments for manage_budget_config: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for manage_budget_config: %s. Args: workspace_id=%s, weights_provided=%s",
            e,
            workspace_id,
            weights is not None,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing manage_budget_config: {type(e).__name__}"
        )


# --- Project Onboarding Tools (Feature 4) ---


@engrams_mcp.tool(
    name="get_project_briefing",
    description="Generates a structured, human-readable project briefing at a specified depth level. Levels: 'executive' (~500 tokens), 'overview' (~2000 tokens), 'detailed' (~5000 tokens), 'comprehensive' (~20000 tokens) — choose based on your token budget; prefer 'executive' for quick orientation and 'detailed' for deep onboarding. Set staleness_only=True to check data freshness without generating content (returns section freshness metadata only, no content); this is a completely different return shape — do not expect sections[].content when staleness_only=True. To drill into one section, pass a single section ID string in the sections parameter. NOT for programmatic context retrieval (use get_product_context or get_relevant_context instead). Returns when staleness_only=False: {level, sections: [{id, title, content}], staleness_info, coverage_stats}. Returns when staleness_only=True: {sections: [{id, last_updated, is_stale}], stale_count} — content field is absent.",
    annotations=ToolAnnotations(
        title="Get Project Briefing",
        readOnlyHint=True,
    ),
)
async def tool_get_project_briefing(
    workspace_id: Annotated[
        str, Field(description="The absolute path to the workspace directory (e.g. '/home/user/myproject'). Used to locate the Engrams database for this workspace.")
    ],
    level: Annotated[
        str,
        Field(
            description="Briefing depth level. Valid values: 'executive' (~500 tokens), 'overview' (~2000 tokens), 'detailed' (~5000 tokens), 'comprehensive' (~20000 tokens)."
        ),
    ],
    staleness_only: Annotated[
        bool,
        Field(description="If True, return only staleness info without generating content (replaces get_briefing_staleness)"),
    ] = False,
    stale_threshold_days: Annotated[
        Optional[Union[int, str]],
        Field(description="Days after which data is considered stale (default: 30)"),
    ] = 30,
    token_budget: Annotated[
        Optional[Union[int, str]],
        Field(
            description="Max token budget for the briefing. Defaults per level "
            "(executive=500, overview=2000, detailed=5000, comprehensive=20000)."
        ),
    ] = None,
    sections: Annotated[
        Optional[List[str]],
        Field(
            description="Optional list of specific section IDs to include "
            "(e.g., ['project_identity', 'key_decisions', 'active_tasks']). "
            "Omit to include all sections for the level."
        ),
    ] = None,
    scope_id: Annotated[
        Optional[Union[int, str]],
        Field(description="Optional governance scope ID for filtering (Feature 1)"),
    ] = None,
) -> Dict[str, Any]:
    """
    Generate a structured project briefing at the specified depth level.

    Args:
        workspace_id: The identifier for the workspace.
        level: Briefing depth level.
        staleness_only: If True, return only staleness info without content.
        stale_threshold_days: Days after which data is considered stale.
        token_budget: Optional max token budget.
        sections: Optional list of section IDs to include.
        scope_id: Optional scope ID for governance filtering.

    Returns:
        A structured briefing with sections, staleness info, and coverage stats.
        Or when staleness_only=True: per-section staleness info and stale count.
    """
    try:
        if staleness_only:
            # Route to staleness handler when staleness_only=True
            args = onboarding_models.GetBriefingStalenessArgs(
                workspace_id=workspace_id,
                stale_threshold_days=(
                    int(stale_threshold_days) if stale_threshold_days is not None else 30
                ),
            )
            return mcp_handlers.handle_get_briefing_staleness(args)
        else:
            # Normal briefing generation path
            args = onboarding_models.GetProjectBriefingArgs(
                workspace_id=workspace_id,
                level=level,
                token_budget=int(token_budget) if token_budget is not None else None,
                sections=sections,
                scope_id=int(scope_id) if scope_id is not None else None,
            )
            return mcp_handlers.handle_get_project_briefing(args)
    except exceptions.ContextPortalError as e:
        log.error("Error in get_project_briefing handler: %s", e)
        raise
    except ValueError as e:
        log.error("Validation error for get_project_briefing: %s", e)
        raise exceptions.ContextPortalError(
            f"Invalid arguments for get_project_briefing: {e}"
        )
    except Exception as e:
        log.error(
            "Error processing args for get_project_briefing: %s. "
            "Args: workspace_id=%s, level='%s', staleness_only=%s",
            e,
            workspace_id,
            level,
            staleness_only,
        )
        raise exceptions.ContextPortalError(
            f"Server error processing get_project_briefing: {type(e).__name__}"
        )




# Mount the FastMCP HTTP app to the FastAPI app at the /mcp path
# This will handle both GET and POST requests using modern HTTP transport
app.mount("/mcp", engrams_mcp.http_app())
log.info("Mounted FastMCP HTTP app at /mcp")


# Keep a simple root endpoint for health checks or basic info
@app.get("/")
async def read_root():
    """Root endpoint for health check."""
    return {"message": "Engrams MCP Server is running. MCP endpoint at /mcp"}


# Determine the absolute path to the root of the Engrams server project
# Assumes this script (main.py) is at src/engrams/main.py
ENGRAMS_SERVER_ROOT_DIR = Path(
    os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
)
log.info("Engrams Server Root Directory identified as: %s", ENGRAMS_SERVER_ROOT_DIR)


def main_logic(sys_args=None):
    """
    Configures and runs the Engrams server (HTTP mode via Uvicorn).
    The actual MCP logic is handled by the FastMCP instance mounted on the FastAPI app.
    """
    parser = argparse.ArgumentParser(description="Engrams MCP Server (FastMCP/HTTP)")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind the HTTP server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the HTTP server to (default: 8000)",
    )
    # Enhanced workspace_id parameter with auto-detection support
    parser.add_argument(
        "--workspace_id",
        type=str,
        required=False,  # No longer strictly required for server startup itself
        help="Workspace ID. If not provided, will auto-detect from current directory "
        "or MCP client context.",
    )

    # New auto-detection parameters
    parser.add_argument(
        "--auto-detect-workspace",
        action="store_true",
        default=True,
        help="Automatically detect workspace from current directory (default: True)",
    )

    parser.add_argument(
        "--workspace-search-start",
        help="Starting directory for workspace detection (default: current directory)",
    )

    parser.add_argument(
        "--no-auto-detect",
        action="store_true",
        help="Disable automatic workspace detection",
    )
    # The --mode argument might be deprecated if FastMCP only runs HTTP this way,
    # or we add a condition here to call engrams_mcp.run(transport="stdio")
    parser.add_argument(
        "--mode",
        choices=[
            "http",
            "stdio",
        ],  # Add http, stdio might be handled by FastMCP directly
        default="http",
        help="Server communication mode (default: http for FastMCP mounted app)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="logs/engrams.log",
        help="Path to a file where logs should be written, relative to the "
        "engrams directory. Defaults to 'logs/engrams.log'.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        required=False,
        help="Custom database file path (absolute or relative to workspace). "
        "Defaults to 'engrams/context.db' in workspace.",
    )
    parser.add_argument(
        "--base-path",
        type=str,
        required=False,
        help="Base path for storing all workspace-specific data. "
        "A subdirectory will be created for each workspace.",
    )
    parser.add_argument(
        "--db-filename",
        type=str,
        default="context.db",
        help="The name of the context database file. Defaults to 'context.db'.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level.",
    )

    args = parser.parse_args(args=sys_args)

    # Configure logging based on the parsed arguments
    setup_logging(args)

    # Set custom database path if provided
    if args.db_path:
        from .core import config

        config.set_custom_db_path(args.db_path)
        log.info("Using custom database path: %s", args.db_path)

    if args.base_path:
        from .core import config

        config.set_base_path(args.base_path)
        log.info("Using base path: %s", args.base_path)

    if args.db_filename:
        from .core import config

        config.set_db_filename(args.db_filename)
        log.info("Using database filename: %s", args.db_filename)

    log.info("Parsed CLI args: %s", args)

    # In stdio mode, we should not configure the console handler,
    # as it can interfere with MCP communication.
    # FastMCP handles stdio, so we only add console logging for http mode.
    if args.mode == "http":
        log.info(
            "Starting Engrams HTTP server (via FastMCP) on %s:%s", args.host, args.port
        )
        # The FastAPI `app` (with FastMCP mounted) is run by Uvicorn
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.mode == "stdio":
        log.info("Starting Engrams in STDIO mode with workspace detection enabled")

        # Resolve workspace ID using the new detection system
        auto_detect_enabled = args.auto_detect_workspace and not args.no_auto_detect
        effective_workspace_id = resolve_workspace_id(
            provided_workspace_id=args.workspace_id,
            auto_detect=auto_detect_enabled,
            start_path=args.workspace_search_start,
        )

        # Log detection details for debugging
        if auto_detect_enabled:
            detector = WorkspaceDetector(args.workspace_search_start)
            detection_info = detector.get_detection_info()
            log.info("Workspace detection details: %s", detection_info)

        log.info("Effective workspace ID: %s", effective_workspace_id)

        # Pre-warm the database connection to trigger one-time initialization (e.g., migrations)
        # before the MCP transport starts. This prevents timeouts on the client's first tool call.
        if effective_workspace_id:
            try:
                log.info(
                    "Pre-warming database connection for workspace: %s",
                    effective_workspace_id,
                )
                database.get_db_connection(effective_workspace_id)
                log.info("Database connection pre-warmed successfully.")
            except Exception as e:  # pylint: disable=broad-exception-caught
                log.error(
                    "Failed to pre-warm database connection for workspace '%s': %s",
                    effective_workspace_id,
                    e,
                )
                # If the DB is essential, exiting is safer than continuing in a broken state.
                sys.exit(1)
        else:
            log.warning(
                "No effective_workspace_id available at startup. "
                "Database initialization will be deferred to the first tool call."
            )

        # Note: The `FastMCP.run()` method is synchronous and will block until the server stops.
        # It requires the `mcp[cli]` extra to be installed for `mcp.server.stdio.run_server_stdio`.
        try:
            # The `settings` attribute on FastMCP can be used to pass runtime config.
            # However, `workspace_id` is not a standard FastMCP setting for `run()`.
            # It's expected to be part of the tool call parameters.
            # The primary role of --workspace_id for stdio here is for the IDE's launch config.
            engrams_mcp.run(transport="stdio")
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Error running FastMCP in STDIO mode")
            sys.exit(1)

    else:
        log.error("Unsupported mode: %s", args.mode)
        sys.exit(1)


def cli_entry_point():
    """Entry point for the 'engrams' command-line script."""
    log.info("Engrams MCP Server CLI entry point called.")
    main_logic()


if __name__ == "__main__":
    cli_entry_point()
