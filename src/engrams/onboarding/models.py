"""Pydantic models for the onboarding feature (Feature 4)."""

from typing import ClassVar, List, Optional, Set
from pydantic import Field, model_validator

from ..db.models import BaseArgs, IntCoercionMixin


class GetProjectBriefingArgs(IntCoercionMixin, BaseArgs):
    """Arguments for get_project_briefing tool."""

    INT_FIELDS: ClassVar[Set[str]] = {"token_budget", "scope_id"}

    level: str = Field(
        ...,
        description="Briefing level: executive, overview, detailed, or comprehensive",
    )
    token_budget: Optional[int] = Field(
        default=None,
        description="Max token budget (defaults per level)",
    )
    sections: Optional[List[str]] = Field(
        default=None,
        description="Specific section IDs to include",
    )
    scope_id: Optional[int] = Field(
        default=None,
        description="Scope ID for filtering (Feature 1)",
    )

    @model_validator(mode="after")
    def validate_level(self) -> "GetProjectBriefingArgs":
        valid_levels = {"executive", "overview", "detailed", "comprehensive"}
        if self.level not in valid_levels:
            raise ValueError(
                f"Invalid level '{self.level}'. Must be one of: {valid_levels}"
            )
        return self


class GetBriefingStalenessArgs(IntCoercionMixin, BaseArgs):
    """Arguments for get_briefing_staleness tool."""

    INT_FIELDS: ClassVar[Set[str]] = {"stale_threshold_days"}

    stale_threshold_days: Optional[int] = Field(
        default=30,
        description="Days after which data is considered stale",
    )

    @model_validator(mode="after")
    def check_threshold(self) -> "GetBriefingStalenessArgs":
        if self.stale_threshold_days is not None and self.stale_threshold_days < 1:
            raise ValueError("stale_threshold_days must be >= 1")
        return self


class GetSectionDetailArgs(IntCoercionMixin, BaseArgs):
    """Arguments for get_section_detail tool."""

    INT_FIELDS: ClassVar[Set[str]] = {"token_budget", "scope_id"}

    section_id: str = Field(
        ...,
        description="Section ID to drill into",
    )
    token_budget: Optional[int] = Field(
        default=None,
        description="Max token budget",
    )
    scope_id: Optional[int] = Field(
        default=None,
        description="Scope ID for filtering",
    )
