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

"""Pydantic models for the budgeting feature (Feature 3)."""

from typing import Dict, List, Optional

from pydantic import Field, model_validator

from ..db.models import BaseArgs, IntCoercionMixin


class GetRelevantContextArgs(IntCoercionMixin, BaseArgs):
    """Arguments for get_relevant_context tool."""

    INT_FIELDS = {"token_budget", "scope_id"}

    task_description: str = Field(..., description="Description of current task")
    token_budget: int = Field(..., description="Maximum token budget", gt=0)
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

    task_description: str = Field(..., description="Description of current task")
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
                raise ValueError(f"Weight {key} must be between 0.0 and 1.0, got {val}")
        return self
