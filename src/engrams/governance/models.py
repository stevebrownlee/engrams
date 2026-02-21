"""Pydantic models for the governance feature (Feature 1)."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

# --- Table Models ---


class ContextScope(BaseModel):
    """Model for the context_scopes table."""

    id: Optional[int] = None
    scope_type: str = Field(..., description="'team' or 'individual'")
    scope_name: str = Field(..., description="Human-readable name")
    parent_scope_id: Optional[int] = None
    created_by: str = Field(..., description="Who created this scope")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GovernanceRule(BaseModel):
    """Model for the governance_rules table."""

    id: Optional[int] = None
    scope_id: int = Field(..., description="References context_scopes.id")
    rule_type: str = Field(
        ..., description="'hard_block', 'soft_warn', 'allow_with_flag'"
    )
    entity_type: str = Field(..., description="Which entity type this rule governs")
    rule_definition: Dict[str, Any] = Field(
        ..., description="Structured rule definition (JSON)"
    )
    description: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScopeAmendment(BaseModel):
    """Model for the scope_amendments table."""

    id: Optional[int] = None
    source_item_type: str
    source_item_id: int
    target_item_type: str
    target_item_id: int
    status: str = Field(
        ..., description="'proposed', 'under_review', 'accepted', 'rejected'"
    )
    rationale: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConflictCheckResult(BaseModel):
    """Result of a conflict detection check."""

    has_conflict: bool = False
    action: str = "allow"  # 'allow', 'warn', 'block'
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    amendments_created: List[int] = Field(default_factory=list)


# --- MCP Tool Argument Models ---


class BaseArgs(BaseModel):
    """Base model requiring workspace_id."""

    workspace_id: str = Field(..., description="Identifier for the workspace")


class CreateScopeArgs(BaseArgs):
    """Arguments for create_scope tool."""

    scope_type: str = Field(..., description="'team' or 'individual'")
    scope_name: str = Field(
        ..., min_length=1, description="Human-readable name for the scope"
    )
    parent_scope_id: Optional[int] = Field(
        None, description="FK to parent scope (for individual under team)"
    )
    created_by: str = Field(..., min_length=1, description="Who is creating this scope")

    @model_validator(mode="after")
    def validate_scope_type(self) -> "CreateScopeArgs":
        if self.scope_type not in ("team", "individual"):
            raise ValueError("scope_type must be 'team' or 'individual'")
        return self


class GetScopesArgs(BaseArgs):
    """Arguments for get_scopes tool."""

    scope_type: Optional[str] = Field(
        None, description="Filter by scope type ('team' or 'individual')"
    )


class LogGovernanceRuleArgs(BaseArgs):
    """Arguments for log_governance_rule tool."""

    scope_id: int = Field(..., description="The scope this rule belongs to")
    rule_type: str = Field(
        ..., description="'hard_block', 'soft_warn', or 'allow_with_flag'"
    )
    entity_type: str = Field(..., description="Entity type this rule governs")
    rule_definition: Dict[str, Any] = Field(
        ..., description="Structured rule definition"
    )
    description: Optional[str] = Field(None, description="Human-readable description")

    @model_validator(mode="after")
    def validate_rule_type(self) -> "LogGovernanceRuleArgs":
        if self.rule_type not in ("hard_block", "soft_warn", "allow_with_flag"):
            raise ValueError(
                "rule_type must be 'hard_block', 'soft_warn', or 'allow_with_flag'"
            )
        return self


class GetGovernanceRulesArgs(BaseArgs):
    """Arguments for get_governance_rules tool."""

    scope_id: int = Field(..., description="Scope to get rules for")
    entity_type: Optional[str] = Field(None, description="Filter by entity type")


class CheckComplianceArgs(BaseArgs):
    """Arguments for check_compliance tool."""

    item_type: str = Field(..., description="Entity type to check")
    item_id: int = Field(..., description="Entity ID to check")


class GetScopeAmendmentsArgs(BaseArgs):
    """Arguments for get_scope_amendments tool."""

    status: Optional[str] = Field(None, description="Filter by status")
    scope_id: Optional[int] = Field(None, description="Filter by scope")


class ReviewAmendmentArgs(BaseArgs):
    """Arguments for review_amendment tool."""

    amendment_id: int = Field(..., description="ID of the amendment to review")
    status: str = Field(..., description="'accepted' or 'rejected'")
    reviewed_by: str = Field(..., min_length=1, description="Who is reviewing")

    @model_validator(mode="after")
    def validate_status(self) -> "ReviewAmendmentArgs":
        if self.status not in ("accepted", "rejected"):
            raise ValueError("status must be 'accepted' or 'rejected'")
        return self


class GetEffectiveContextArgs(BaseArgs):
    """Arguments for get_effective_context tool."""

    scope_id: int = Field(
        ..., description="Individual scope ID to get effective context for"
    )
