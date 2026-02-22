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

"""Token estimation for Engrams entities (Feature 3).

Uses a simple heuristic: token_count ≈ len(text) / 4 for English text.
Optionally supports tiktoken if installed.
"""

import json
import logging
from typing import Any, Dict

log = logging.getLogger(__name__)

# Try to import tiktoken for more accurate estimation
_tiktoken_available = False
_tiktoken_encoding = None

try:
    import tiktoken

    _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
    _tiktoken_available = True
    log.debug("tiktoken available for accurate token estimation")
except ImportError:
    log.debug("tiktoken not available, using heuristic token estimation")


def estimate_tokens(entity: Dict[str, Any], format: str = "compact") -> int:
    """
    Estimate token count for a Engrams entity.

    Formats:
    - "compact": Minimal representation (type, summary, key fields only)
    - "standard": Full content without metadata
    - "verbose": Everything including rationale, implementation details, links

    Args:
        entity: Dictionary representation of a Engrams entity.
        format: Output format affecting which fields are included.

    Returns:
        Estimated token count.
    """
    text = _format_entity(entity, format)
    return _count_tokens(text)


def estimate_text_tokens(text: str) -> int:
    """Estimate tokens for a raw text string."""
    return _count_tokens(text)


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken if available, heuristic otherwise."""
    if _tiktoken_available and _tiktoken_encoding:
        try:
            return len(_tiktoken_encoding.encode(text))
        except Exception:
            pass
    # Heuristic: ~4 characters per token for English text
    return max(1, len(text) // 4)


def _format_entity(entity: Dict[str, Any], format: str) -> str:
    """Format an entity into text for token estimation."""
    parts = []
    entity_type = entity.get("_type", entity.get("type", "unknown"))

    if format == "compact":
        # Minimal: type + key identifier field
        parts.append(f"[{entity_type}]")
        for field in ["summary", "name", "description", "key"]:
            if entity.get(field):
                parts.append(str(entity[field]))
                break
        if entity.get("tags"):
            tags = entity["tags"]
            if isinstance(tags, list):
                parts.append(f"tags: {', '.join(tags)}")
            else:
                parts.append(f"tags: {tags}")

    elif format == "standard":
        parts.append(f"[{entity_type}]")
        for field in ["summary", "name", "description", "key", "status"]:
            if entity.get(field):
                parts.append(f"{field}: {entity[field]}")
        if entity.get("rationale"):
            parts.append(f"rationale: {entity['rationale']}")
        if entity.get("tags"):
            tags = entity["tags"]
            if isinstance(tags, list):
                parts.append(f"tags: {', '.join(tags)}")
            else:
                parts.append(f"tags: {tags}")
        if entity.get("value"):
            val = entity["value"]
            val_str = json.dumps(val) if not isinstance(val, str) else val
            if len(val_str) > 500:
                val_str = val_str[:500] + "..."
            parts.append(f"value: {val_str}")

    elif format == "verbose":
        # Everything
        for key, value in entity.items():
            if key.startswith("_") or value is None:
                continue
            val_str = json.dumps(value) if not isinstance(value, str) else value
            parts.append(f"{key}: {val_str}")

    return "\n".join(parts)
