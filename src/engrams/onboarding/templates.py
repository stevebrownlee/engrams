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

"""Section templates and ordering for project briefings (Feature 4)."""

from typing import Any, Dict, List, Optional

# Briefing levels ordered by depth
BRIEFING_LEVELS = ["executive", "overview", "detailed", "comprehensive"]

# Level to minimum index mapping for section inclusion
LEVEL_DEPTH = {
    "executive": 0,
    "overview": 1,
    "detailed": 2,
    "comprehensive": 3,
}

# Default token budgets per level
DEFAULT_LEVEL_BUDGETS = {
    "executive": 500,
    "overview": 2000,
    "detailed": 5000,
    "comprehensive": 20000,
}

BRIEFING_SECTIONS: List[Dict[str, Any]] = [
    {
        "id": "project_identity",
        "title": "Project Overview",
        "min_level": "executive",
        "source": "product_context",
        "description": "What this project is, who it's for, what problem it solves",
    },
    {
        "id": "current_status",
        "title": "Current Status",
        "min_level": "executive",
        "source": "active_context",
        "description": "What's being worked on now, recent changes, blockers",
    },
    {
        "id": "architecture",
        "title": "Architecture & Technical Stack",
        "min_level": "overview",
        "source": "product_context+system_patterns",
        "description": "How the system is built, key architectural decisions",
    },
    {
        "id": "key_decisions",
        "title": "Key Decisions",
        "min_level": "overview",
        "source": "decisions_top",
        "description": "The most important decisions that shape the project",
    },
    {
        "id": "team_conventions",
        "title": "Team Conventions & Rules",
        "min_level": "overview",
        "source": "governance_rules+team_patterns",
        "description": "What the team has agreed to follow",
        "requires_feature": "governance",
    },
    {
        "id": "active_tasks",
        "title": "Active Work",
        "min_level": "overview",
        "source": "progress_active",
        "description": "What's in progress, what's blocked, what's next",
    },
    {
        "id": "risks_and_concerns",
        "title": "Known Risks & Open Questions",
        "min_level": "overview",
        "source": "custom_data_risks+decisions_risks",
        "description": "What could go wrong, what's unresolved",
    },
    {
        "id": "all_decisions",
        "title": "Decision Log",
        "min_level": "detailed",
        "source": "decisions_all",
        "description": "Complete list of active decisions with rationale",
    },
    {
        "id": "patterns",
        "title": "System Patterns",
        "min_level": "detailed",
        "source": "system_patterns_all",
        "description": "Documented patterns with implementation guidance",
    },
    {
        "id": "glossary",
        "title": "Project Glossary",
        "min_level": "detailed",
        "source": "custom_data_glossary",
        "description": "Domain-specific terminology",
    },
    {
        "id": "knowledge_graph",
        "title": "Entity Relationships",
        "min_level": "comprehensive",
        "source": "engrams_item_links",
        "description": "How decisions, patterns, tasks, and code relate to each other",
    },
]


def get_sections_for_level(
    level: str, section_filter: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Get sections appropriate for the given briefing level.

    Args:
        level: The briefing level (executive/overview/detailed/comprehensive).
        section_filter: Optional list of section IDs to include.

    Returns:
        List of section definition dicts for the requested level.
    """
    level_depth = LEVEL_DEPTH.get(level, 1)
    sections = []
    for section in BRIEFING_SECTIONS:
        section_depth = LEVEL_DEPTH.get(section["min_level"], 0)
        if section_depth <= level_depth:
            if section_filter is None or section["id"] in section_filter:
                sections.append(section)
    return sections


def get_default_budget(level: str) -> int:
    """Get default token budget for a briefing level.

    Args:
        level: The briefing level.

    Returns:
        Default token budget integer.
    """
    return DEFAULT_LEVEL_BUDGETS.get(level, 2000)
