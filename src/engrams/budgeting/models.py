"""Pydantic models for the budgeting feature (Feature 3)."""

from typing import Dict, List, Optional
from pydantic import Field, model_validator

from ..db.models import BaseArgs, IntCoercionMixin


class GetRelevantContextArgs(IntCoercionMixin, BaseArgs):
    """Arguments for get_relevant_context tool."""

    INT_FIELDS = {"token_budget", "scope_id"}

    task_description: str = Field(
        ..., description="Description of current task"
    )
    token_budget: int = Field(
        ..., description="Maximum token budget", gt=0
    )
    profile: Optional[str] = Field(
        default="task_focused",
        description="Scoring profile name",
    )
    file_paths: Optional[List[str]] = Field(
        default=None,
        description="Files being edited for code proximity scoring",
    )
    scope_id: Optional[int] = Field(
        default=None,
        description="Scope ID for filtering",
    )
    format: Optional[str] = Field(
        default="standard",
        description="Entity format: compact, standard, or verbose",
    )


class EstimateContextSizeArgs(BaseArgs):
    """Arguments for estimate_context_size tool."""

    task_description: str = Field(
        ..., description="Description of current task"
    )
    profile: Optional[str] = Field(
        default="task_focused",
        description="Scoring profile name",
    )


class GetContextBudgetConfigArgs(BaseArgs):
    """Arguments for get_context_budget_config tool."""



class UpdateContextBudgetConfigArgs(BaseArgs):
    """Arguments for update_context_budget_config tool."""

    weights: Dict[str, float] = Field(
        ..., description="Weight overrides for scoring factors"
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "UpdateContextBudgetConfigArgs":
        valid_factors = {
            "semantic_similarity",
            "recency",
            "reference_frequency",
            "lifecycle_status",
            "scope_priority",
            "code_proximity",
            "explicit_priority",
        }
        for key, val in self.weights.items():
            if key not in valid_factors:
                raise ValueError(
                    f"Unknown weight factor: {key}. Valid: {valid_factors}"
                )
            if not 0.0 <= val <= 1.0:
                raise ValueError(
                    f"Weight {key} must be between 0.0 and 1.0, got {val}"
                )
        return self
