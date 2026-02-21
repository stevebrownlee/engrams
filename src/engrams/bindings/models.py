"""Pydantic models for the code bindings feature (Feature 2)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

# --- Table Models ---


class CodeBinding(BaseModel):
    """Model for the code_bindings table."""

    id: Optional[int] = None
    item_type: str = Field(..., description="Engrams entity type")
    item_id: int = Field(..., description="ID of the Engrams entity")
    file_pattern: str = Field(..., description="Glob or path pattern")
    symbol_pattern: Optional[str] = Field(
        None, description="Optional function/class name pattern"
    )
    binding_type: str = Field(
        ...,
        description="'implements', 'governed_by', 'tests', 'documents', 'configures'",
    )
    confidence: str = Field(
        default="manual", description="'manual', 'agent_suggested', 'auto_detected'"
    )
    last_verified_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CodeBindingVerification(BaseModel):
    """Model for the code_binding_verifications table."""

    id: Optional[int] = None
    binding_id: int
    verification_status: str = Field(
        ..., description="'valid', 'file_missing', 'symbol_not_found', 'pattern_empty'"
    )
    files_matched: Optional[int] = None
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None


class BindingWithContext(BaseModel):
    """A binding with its associated Engrams entity data for get_context_for_files."""

    binding: CodeBinding
    entity_type: str
    entity_id: int
    entity_summary: str = ""
    binding_type: str = ""
    confidence: str = "manual"
    governance_info: Optional[Dict[str, Any]] = None


# --- MCP Tool Argument Models ---


class BaseArgs(BaseModel):
    """Base model requiring workspace_id."""

    workspace_id: str = Field(..., description="Identifier for the workspace")


class BindCodeToItemArgs(BaseArgs):
    """Arguments for bind_code_to_item tool."""

    item_type: str = Field(..., description="Engrams entity type")
    item_id: int = Field(..., description="Entity ID")
    file_pattern: str = Field(..., min_length=1, description="Glob or path pattern")
    symbol_pattern: Optional[str] = Field(None, description="Optional symbol pattern")
    binding_type: str = Field(..., description="Nature of the binding")
    confidence: str = Field(default="manual", description="Confidence level")

    @model_validator(mode="after")
    def validate_binding_type(self) -> "BindCodeToItemArgs":
        valid = ("implements", "governed_by", "tests", "documents", "configures")
        if self.binding_type not in valid:
            raise ValueError(f"binding_type must be one of {valid}")
        return self


class GetBindingsForItemArgs(BaseArgs):
    """Arguments for get_bindings_for_item tool."""

    item_type: str = Field(..., description="Engrams entity type")
    item_id: int = Field(..., description="Entity ID")


class GetContextForFilesArgs(BaseArgs):
    """Arguments for get_context_for_files tool."""

    file_paths: List[str] = Field(..., description="List of file paths being edited")
    binding_type_filter: Optional[str] = Field(
        None, description="Filter by binding type"
    )


class VerifyBindingsArgs(BaseArgs):
    """Arguments for verify_bindings tool."""

    item_type: Optional[str] = Field(None, description="Filter by entity type")
    item_id: Optional[int] = Field(None, description="Filter by entity ID")


class GetStaleBindingsArgs(BaseArgs):
    """Arguments for get_stale_bindings tool."""

    days_stale: int = Field(default=30, description="Days since last verification")


class SuggestBindingsArgs(BaseArgs):
    """Arguments for suggest_bindings tool."""

    item_type: str = Field(..., description="Engrams entity type")
    item_id: int = Field(..., description="Entity ID")


class UnbindCodeFromItemArgs(BaseArgs):
    """Arguments for unbind_code_from_item tool."""

    binding_id: int = Field(..., description="ID of the binding to remove")
