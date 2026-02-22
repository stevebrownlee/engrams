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

"""Predefined context profiles for common scenarios (Feature 3)."""

from typing import Dict

# Default scoring weights
DEFAULT_WEIGHTS: Dict[str, float] = {
    "semantic_similarity": 0.30,
    "recency": 0.15,
    "reference_frequency": 0.15,
    "lifecycle_status": 0.15,
    "scope_priority": 0.10,
    "code_proximity": 0.10,
    "explicit_priority": 0.05,
}

PROFILES: Dict[str, Dict[str, float]] = {
    "task_focused": {
        "semantic_similarity": 0.40,
        "recency": 0.10,
        "reference_frequency": 0.10,
        "lifecycle_status": 0.05,
        "scope_priority": 0.05,
        "code_proximity": 0.25,
        "explicit_priority": 0.05,
    },
    "architectural_overview": {
        "semantic_similarity": 0.15,
        "recency": 0.05,
        "reference_frequency": 0.25,
        "lifecycle_status": 0.15,
        "scope_priority": 0.25,
        "code_proximity": 0.05,
        "explicit_priority": 0.10,
    },
    "onboarding": {
        "semantic_similarity": 0.20,
        "recency": 0.10,
        "reference_frequency": 0.25,
        "lifecycle_status": 0.15,
        "scope_priority": 0.10,
        "code_proximity": 0.05,
        "explicit_priority": 0.15,
    },
    "review": {
        "semantic_similarity": 0.15,
        "recency": 0.10,
        "reference_frequency": 0.10,
        "lifecycle_status": 0.25,
        "scope_priority": 0.20,
        "code_proximity": 0.15,
        "explicit_priority": 0.05,
    },
}

# Default token budgets per briefing level
DEFAULT_BUDGETS = {
    "minimal": 1000,
    "standard": 4000,
    "comprehensive": 10000,
}


def get_profile_weights(profile_name: str) -> Dict[str, float]:
    """Get the scoring weights for a named profile."""
    if profile_name == "custom":
        return DEFAULT_WEIGHTS.copy()
    return PROFILES.get(profile_name, DEFAULT_WEIGHTS).copy()
