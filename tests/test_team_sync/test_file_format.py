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

"""Tests for Phase 1: filesystem-first file format + parser.

Covers:
- Round-trip: serialize → write temp file → parse → re-serialize → compare
- All entity types: Decision, SystemPattern, custom-data
- All binding types ("implements", "governed_by", "tests", "documents", "configures")
- Optional symbol field present/absent
- Empty bindings list
- Manifest helpers (compute_file_hash, load/save/update)
- Hypothesis property-based tests for Decision and Pattern round-trips
"""

import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

# ---------------------------------------------------------------------------
# Hypothesis imports — skip property-based tests if not installed
# ---------------------------------------------------------------------------
try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st

    HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    HYPOTHESIS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Modules under test
# ---------------------------------------------------------------------------
from engrams.bindings.models import CodeBinding
from engrams.db.models import Decision, SystemPattern
from engrams.team_sync.manifest import (
    MANIFEST_FILENAME,
    compute_file_hash,
    load_manifest,
    save_manifest,
    update_manifest_entry,
)
from engrams.team_sync.models import (
    DecisionFrontmatter,
    FrontmatterBinding,
    Manifest,
    ManifestEntry,
    PatternFrontmatter,
    SharedDataFrontmatter,
)
from engrams.team_sync.parser import (
    frontmatter_to_bindings,
    parse_decision_file,
    parse_pattern_file,
    parse_shared_data_file,
)
from engrams.team_sync.serializer import (
    custom_data_to_markdown,
    decision_to_markdown,
    make_decision_filename,
    make_pattern_filename,
    make_shared_data_filename,
    pattern_to_markdown,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_BINDING_TYPES = ["implements", "governed_by", "tests", "documents", "configures"]

NOW = datetime.now(timezone.utc)


# Sentinel to distinguish "caller passed no tags arg" from "caller passed tags=[]"
_NO_TAGS = object()


def _make_decision(
    *,
    summary: str = "Use PostgreSQL for production",
    rationale: Optional[str] = "Strong JSONB support",
    impl: Optional[str] = "Need connection pooling",
    tags: Any = _NO_TAGS,
    decision_uuid: Optional[str] = None,
    id_: Optional[int] = 1,
) -> Decision:
    resolved_tags = ["database", "infrastructure"] if tags is _NO_TAGS else list(tags)
    return Decision(
        id=id_,
        uuid=decision_uuid or str(uuid.uuid4()),
        summary=summary,
        rationale=rationale,
        implementation_details=impl,
        tags=resolved_tags,
        timestamp=NOW,
        visibility="team",
    )


def _make_pattern(
    *,
    name: str = "Repository Pattern",
    description: Optional[str] = "Centralise data access through repository classes.",
    tags: Optional[List[str]] = None,
    pattern_uuid: Optional[str] = None,
    id_: Optional[int] = 1,
) -> SystemPattern:
    # SystemPattern in the DB model doesn't have a uuid field yet (Phase 4),
    # so we attach it as a dynamic attribute for our tests using object.__setattr__
    # to sidestep Pydantic's frozen-model guard (model_config default allows it).
    p = SystemPattern(
        id=id_,
        name=name,
        description=description,
        tags=tags or ["architecture", "data-access"],
        timestamp=NOW,
        visibility="team",
    )
    object.__setattr__(p, "uuid", pattern_uuid or str(uuid.uuid4()))
    return p


def _make_binding(
    binding_type: str = "implements",
    file_pattern: str = "src/db/**/*.py",
    symbol: Optional[str] = None,
    item_id: int = 1,
    item_type: str = "decision",
) -> CodeBinding:
    return CodeBinding(
        item_type=item_type,
        item_id=item_id,
        file_pattern=file_pattern,
        symbol_pattern=symbol,
        binding_type=binding_type,
        confidence="manual",
    )


def _write_and_parse_decision(
    decision: Decision, bindings: List[CodeBinding]
) -> Tuple[DecisionFrontmatter, str]:
    md = decision_to_markdown(decision, bindings)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(md)
        tmp = Path(f.name)
    try:
        return parse_decision_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _write_and_parse_pattern(
    pattern: SystemPattern, bindings: List[CodeBinding]
) -> Tuple[PatternFrontmatter, str]:
    md = pattern_to_markdown(pattern, bindings)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(md)
        tmp = Path(f.name)
    try:
        return parse_pattern_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _write_and_parse_shared_data(
    category: str, entries: List[Tuple[str, Any]]
) -> Tuple[SharedDataFrontmatter, Dict[str, Any]]:
    md = custom_data_to_markdown(category, entries)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(md)
        tmp = Path(f.name)
    try:
        return parse_shared_data_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ===========================================================================
# Decision round-trip tests
# ===========================================================================


class TestDecisionRoundTrip:
    def test_basic_round_trip(self) -> None:
        d = _make_decision()
        fm, _body = _write_and_parse_decision(d, [])
        assert fm.uuid == d.uuid
        assert fm.title == d.summary
        assert fm.tags == d.tags
        assert fm.status == "accepted"
        assert fm.bindings == []

    def test_uuid_preserved(self) -> None:
        specific_uuid = "550e8400-e29b-41d4-a716-446655440000"
        d = _make_decision(decision_uuid=specific_uuid)
        fm, _ = _write_and_parse_decision(d, [])
        assert fm.uuid == specific_uuid

    def test_tags_preserved(self) -> None:
        d = _make_decision(tags=["alpha", "beta", "gamma"])
        fm, _ = _write_and_parse_decision(d, [])
        assert fm.tags == ["alpha", "beta", "gamma"]

    def test_empty_tags(self) -> None:
        d = _make_decision(tags=[])
        fm, _ = _write_and_parse_decision(d, [])
        assert fm.tags == []

    def test_rationale_in_body(self) -> None:
        d = _make_decision(rationale="Because reasons.")
        _md = decision_to_markdown(d, [])
        assert "Because reasons." in _md

    def test_implementation_details_in_body(self) -> None:
        d = _make_decision(impl="Need PgBouncer.")
        _md = decision_to_markdown(d, [])
        assert "Need PgBouncer." in _md

    def test_no_rationale(self) -> None:
        d = _make_decision(rationale=None)
        fm, _ = _write_and_parse_decision(d, [])
        assert fm.title == d.summary

    def test_no_implementation_details(self) -> None:
        d = _make_decision(impl=None)
        fm, _ = _write_and_parse_decision(d, [])
        assert fm.title == d.summary

    def test_bindings_round_trip(self) -> None:
        d = _make_decision()
        b = _make_binding("implements", "src/db/**/*.py")
        fm, _ = _write_and_parse_decision(d, [b])
        assert len(fm.bindings) == 1
        assert fm.bindings[0].pattern == "src/db/**/*.py"
        assert fm.bindings[0].type == "implements"
        assert fm.bindings[0].symbol is None

    def test_binding_with_symbol(self) -> None:
        d = _make_decision()
        b = _make_binding("implements", "src/db/models.py", symbol="DatabaseEngine")
        fm, _ = _write_and_parse_decision(d, [b])
        assert fm.bindings[0].symbol == "DatabaseEngine"

    def test_binding_without_symbol(self) -> None:
        d = _make_decision()
        b = _make_binding("tests", "tests/test_db/**/*.py", symbol=None)
        fm, _ = _write_and_parse_decision(d, [b])
        assert fm.bindings[0].symbol is None

    @pytest.mark.parametrize("btype", VALID_BINDING_TYPES)
    def test_all_binding_types(self, btype: str) -> None:
        d = _make_decision()
        b = _make_binding(btype, "some/path/**/*.py")
        fm, _ = _write_and_parse_decision(d, [b])
        assert fm.bindings[0].type == btype

    def test_multiple_bindings(self) -> None:
        d = _make_decision()
        bindings = [
            _make_binding("implements", "src/db/**/*.py"),
            _make_binding("implements", "src/db/models.py", symbol="DatabaseEngine"),
            _make_binding("tests", "tests/test_db/**/*.py"),
            _make_binding("configures", "alembic/**/*.py"),
        ]
        fm, _ = _write_and_parse_decision(d, bindings)
        assert len(fm.bindings) == 4
        patterns = [b.pattern for b in fm.bindings]
        assert "src/db/**/*.py" in patterns
        assert "alembic/**/*.py" in patterns


# ===========================================================================
# Pattern round-trip tests
# ===========================================================================


class TestPatternRoundTrip:
    def test_basic_round_trip(self) -> None:
        p = _make_pattern()
        fm, _body = _write_and_parse_pattern(p, [])
        assert fm.name == p.name
        assert fm.tags == p.tags
        assert fm.bindings == []

    def test_uuid_preserved(self) -> None:
        specific_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        p = _make_pattern(pattern_uuid=specific_uuid)
        fm, _ = _write_and_parse_pattern(p, [])
        assert fm.uuid == specific_uuid

    def test_description_in_body(self) -> None:
        p = _make_pattern(description="Centralise data access.")
        md = pattern_to_markdown(p, [])
        assert "Centralise data access." in md

    def test_no_description(self) -> None:
        p = _make_pattern(description=None)
        fm, _ = _write_and_parse_pattern(p, [])
        assert fm.name == p.name

    def test_tags_preserved(self) -> None:
        p = _make_pattern(tags=["x", "y"])
        fm, _ = _write_and_parse_pattern(p, [])
        assert fm.tags == ["x", "y"]

    def test_bindings_round_trip(self) -> None:
        p = _make_pattern()
        b = _make_binding("implements", "src/**/repository.py", item_type="system_pattern")
        fm, _ = _write_and_parse_pattern(p, [b])
        assert len(fm.bindings) == 1
        assert fm.bindings[0].pattern == "src/**/repository.py"

    @pytest.mark.parametrize("btype", VALID_BINDING_TYPES)
    def test_all_binding_types(self, btype: str) -> None:
        p = _make_pattern()
        b = _make_binding(btype, "src/**/*.py", item_type="system_pattern")
        fm, _ = _write_and_parse_pattern(p, [b])
        assert fm.bindings[0].type == btype

    def test_symbol_optional_present(self) -> None:
        p = _make_pattern()
        b = _make_binding("implements", "src/db/repo.py", symbol="UserRepo", item_type="system_pattern")
        fm, _ = _write_and_parse_pattern(p, [b])
        assert fm.bindings[0].symbol == "UserRepo"

    def test_symbol_optional_absent(self) -> None:
        p = _make_pattern()
        b = _make_binding("implements", "src/db/repo.py", symbol=None, item_type="system_pattern")
        fm, _ = _write_and_parse_pattern(p, [b])
        assert fm.bindings[0].symbol is None


# ===========================================================================
# Shared-data round-trip tests
# ===========================================================================


class TestSharedDataRoundTrip:
    def test_string_value(self) -> None:
        entries = [("API Gateway", "The single entry point")]
        fm, parsed = _write_and_parse_shared_data("ProjectGlossary", entries)
        assert fm.category == "ProjectGlossary"
        assert parsed["API Gateway"] == "The single entry point"

    def test_numeric_value(self) -> None:
        entries = [("MaxRetries", 5)]
        fm, parsed = _write_and_parse_shared_data("critical_settings", entries)
        assert parsed["MaxRetries"] == 5

    def test_dict_value(self) -> None:
        value = {"host": "localhost", "port": 5432}
        entries = [("DBConfig", value)]
        fm, parsed = _write_and_parse_shared_data("critical_settings", entries)
        assert parsed["DBConfig"] == value

    def test_list_value(self) -> None:
        entries = [("allowed_origins", ["http://localhost:3000", "https://app.example.com"])]
        fm, parsed = _write_and_parse_shared_data("settings", entries)
        assert parsed["allowed_origins"] == ["http://localhost:3000", "https://app.example.com"]

    def test_multiple_entries(self) -> None:
        entries = [
            ("TermA", "Definition A"),
            ("TermB", "Definition B"),
            ("TermC", 42),
        ]
        fm, parsed = _write_and_parse_shared_data("ProjectGlossary", entries)
        assert len(parsed) == 3
        assert parsed["TermA"] == "Definition A"
        assert parsed["TermB"] == "Definition B"
        assert parsed["TermC"] == 42

    def test_empty_entries(self) -> None:
        fm, parsed = _write_and_parse_shared_data("EmptyCategory", [])
        assert fm.category == "EmptyCategory"
        assert parsed == {}

    def test_null_value(self) -> None:
        entries = [("NullKey", None)]
        fm, parsed = _write_and_parse_shared_data("settings", entries)
        assert parsed["NullKey"] is None

    def test_nested_dict_value(self) -> None:
        value = {"db": {"host": "localhost", "credentials": {"user": "admin"}}}
        entries = [("ComplexSetting", value)]
        fm, parsed = _write_and_parse_shared_data("settings", entries)
        assert parsed["ComplexSetting"] == value

    def test_boolean_value(self) -> None:
        entries = [("FeatureFlag", True)]
        fm, parsed = _write_and_parse_shared_data("features", entries)
        assert parsed["FeatureFlag"] is True


# ===========================================================================
# FrontmatterBinding ↔ CodeBinding conversion
# ===========================================================================


class TestFrontmatterToBindings:
    def test_basic_conversion(self) -> None:
        fb = FrontmatterBinding(pattern="src/**/*.py", type="implements")
        bindings = frontmatter_to_bindings(
            entity_uuid="test-uuid",
            entity_type="decision",
            entity_id=42,
            fb_list=[fb],
        )
        assert len(bindings) == 1
        assert bindings[0].file_pattern == "src/**/*.py"
        assert bindings[0].binding_type == "implements"
        assert bindings[0].item_type == "decision"
        assert bindings[0].item_id == 42
        assert bindings[0].confidence == "manual"
        assert bindings[0].last_verified_at is None

    def test_symbol_preserved(self) -> None:
        fb = FrontmatterBinding(pattern="src/db.py", type="implements", symbol="DBClass")
        bindings = frontmatter_to_bindings("uuid", "decision", 1, [fb])
        assert bindings[0].symbol_pattern == "DBClass"

    def test_no_symbol(self) -> None:
        fb = FrontmatterBinding(pattern="src/db.py", type="tests")
        bindings = frontmatter_to_bindings("uuid", "decision", 1, [fb])
        assert bindings[0].symbol_pattern is None

    def test_empty_list(self) -> None:
        bindings = frontmatter_to_bindings("uuid", "decision", 1, [])
        assert bindings == []

    @pytest.mark.parametrize("btype", VALID_BINDING_TYPES)
    def test_all_binding_types_convert(self, btype: str) -> None:
        fb = FrontmatterBinding(pattern="any/**/*.py", type=btype)
        bindings = frontmatter_to_bindings("uuid", "decision", 1, [fb])
        assert bindings[0].binding_type == btype

    def test_system_pattern_entity_type(self) -> None:
        fb = FrontmatterBinding(pattern="src/**/repo.py", type="implements")
        bindings = frontmatter_to_bindings("uuid", "system_pattern", 7, [fb])
        assert bindings[0].item_type == "system_pattern"
        assert bindings[0].item_id == 7


# ===========================================================================
# File naming convention
# ===========================================================================


class TestFileNaming:
    def test_decision_filename_padded(self) -> None:
        d = _make_decision(summary="Use PostgreSQL for Production", id_=1)
        assert make_decision_filename(d) == "001-use-postgresql-for-production.md"

    def test_decision_filename_large_id(self) -> None:
        d = _make_decision(summary="My Decision", id_=42)
        assert make_decision_filename(d) == "042-my-decision.md"

    def test_decision_filename_no_id(self) -> None:
        d = _make_decision(summary="No ID Decision", id_=None)
        assert make_decision_filename(d) == "000-no-id-decision.md"

    def test_pattern_filename(self) -> None:
        p = _make_pattern(name="Repository Pattern")
        assert make_pattern_filename(p) == "repository-pattern.md"

    def test_shared_data_filename(self) -> None:
        assert make_shared_data_filename("ProjectGlossary") == "projectglossary.md"

    def test_slugify_special_chars(self) -> None:
        d = _make_decision(summary="Use API v2.0 & REST!", id_=5)
        fname = make_decision_filename(d)
        assert fname == "005-use-api-v2-0-rest.md"


# ===========================================================================
# UUID in frontmatter matches UUID in filename convention
# ===========================================================================


class TestUUIDConsistency:
    def test_uuid_in_frontmatter_not_filename(self) -> None:
        """The UUID lives in frontmatter; filenames use seq+slug, not UUID."""
        specific_uuid = "550e8400-e29b-41d4-a716-446655440000"
        d = _make_decision(decision_uuid=specific_uuid)
        fname = make_decision_filename(d)
        # filename must NOT contain the UUID
        assert specific_uuid not in fname
        # but frontmatter must contain it
        md = decision_to_markdown(d, [])
        assert specific_uuid in md

    def test_parsed_uuid_matches_original(self) -> None:
        specific_uuid = str(uuid.uuid4())
        d = _make_decision(decision_uuid=specific_uuid)
        fm, _ = _write_and_parse_decision(d, [])
        assert fm.uuid == specific_uuid


# ===========================================================================
# Error handling
# ===========================================================================


class TestParserErrors:
    def test_missing_frontmatter_raises(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# No frontmatter here\n\nJust body text.\n")
            tmp = Path(f.name)
        try:
            with pytest.raises(ValueError, match="frontmatter"):
                parse_decision_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_malformed_yaml_raises(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("---\nuuid: [unclosed\n---\n\nBody\n")
            tmp = Path(f.name)
        try:
            with pytest.raises(ValueError):
                parse_decision_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_missing_required_field_raises(self) -> None:
        """A decision file without ``uuid`` must raise ValidationError."""
        from pydantic import ValidationError

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            # uuid is required — omit it
            f.write("---\ntitle: No UUID decision\nstatus: accepted\n---\n\nBody\n")
            tmp = Path(f.name)
        try:
            with pytest.raises(ValidationError):
                parse_decision_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)


# ===========================================================================
# Manifest helpers
# ===========================================================================


class TestManifest:
    def test_compute_file_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "test.md"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert compute_file_hash(f) == expected

    def test_hash_differs_for_different_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text("content A", encoding="utf-8")
        f2.write_text("content B", encoding="utf-8")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_load_missing_manifest_returns_empty(self, tmp_path: Path) -> None:
        m = load_manifest(tmp_path)
        assert isinstance(m, Manifest)
        assert m.entries == {}
        assert m.version == 1

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        m = Manifest()
        update_manifest_entry(m, "uuid-1", ".engrams/decisions/001-foo.md", "decision", "abc123")
        save_manifest(tmp_path, m)
        loaded = load_manifest(tmp_path)
        assert "uuid-1" in loaded.entries
        assert loaded.entries["uuid-1"].file_path == ".engrams/decisions/001-foo.md"
        assert loaded.entries["uuid-1"].content_hash == "abc123"
        assert loaded.entries["uuid-1"].entity_type == "decision"

    def test_update_manifest_entry_upsert(self, tmp_path: Path) -> None:
        m = Manifest()
        update_manifest_entry(m, "uuid-x", "path/a.md", "decision", "hash1")
        assert m.entries["uuid-x"].content_hash == "hash1"
        # Upsert — update the hash
        update_manifest_entry(m, "uuid-x", "path/a.md", "decision", "hash2")
        assert m.entries["uuid-x"].content_hash == "hash2"
        assert len(m.entries) == 1

    def test_manifest_file_is_pretty_json(self, tmp_path: Path) -> None:
        m = Manifest()
        update_manifest_entry(m, "uuid-1", "path/a.md", "decision", "hashABC")
        save_manifest(tmp_path, m)
        raw = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
        # Pretty-printed → must have newlines and indentation
        assert "\n" in raw
        assert "  " in raw

    def test_load_malformed_manifest_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / MANIFEST_FILENAME
        bad.write_text("this is not json {{", encoding="utf-8")
        m = load_manifest(tmp_path)
        assert m.entries == {}

    def test_manifest_creates_parent_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "new_dir" / "subdir"
        m = Manifest()
        save_manifest(nested, m)
        assert (nested / MANIFEST_FILENAME).exists()


# ===========================================================================
# Double serialise → parse → serialise stability
# ===========================================================================


class TestSerializeStability:
    """Verify that serialise → parse → re-serialise produces identical output."""

    def test_decision_stable(self) -> None:
        d = _make_decision()
        b = _make_binding("implements", "src/**/*.py", symbol="Foo")
        md1 = decision_to_markdown(d, [b])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(md1)
            tmp = Path(f.name)
        try:
            fm, body = parse_decision_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)

        # Reconstruct a Decision from the parsed frontmatter
        d2 = Decision(
            id=d.id,
            uuid=fm.uuid,
            summary=fm.title,
            rationale=d.rationale,
            implementation_details=d.implementation_details,
            tags=fm.tags,
            timestamp=fm.created,
            visibility="team",
        )
        # Reconstruct bindings
        bindings2 = [
            CodeBinding(
                item_type="decision",
                item_id=d.id or 0,
                file_pattern=b2.pattern,
                symbol_pattern=b2.symbol,
                binding_type=b2.type,
                confidence="manual",
            )
            for b2 in fm.bindings
        ]
        md2 = decision_to_markdown(d2, bindings2)

        # Both markdown strings should have the same frontmatter content
        fm1 = yaml.safe_load(md1.split("---")[1])
        fm2 = yaml.safe_load(md2.split("---")[1])
        assert fm1["uuid"] == fm2["uuid"]
        assert fm1["title"] == fm2["title"]
        assert fm1["tags"] == fm2["tags"]
        assert fm1["bindings"] == fm2["bindings"]

    def test_pattern_stable(self) -> None:
        p = _make_pattern()
        b = _make_binding("implements", "src/**/repo.py", item_type="system_pattern")
        md1 = pattern_to_markdown(p, [b])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(md1)
            tmp = Path(f.name)
        try:
            fm, _body = parse_pattern_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)

        p2 = _make_pattern(name=fm.name, tags=fm.tags, pattern_uuid=fm.uuid, id_=p.id)
        bindings2 = [
            CodeBinding(
                item_type="system_pattern",
                item_id=p.id or 0,
                file_pattern=b2.pattern,
                symbol_pattern=b2.symbol,
                binding_type=b2.type,
                confidence="manual",
            )
            for b2 in fm.bindings
        ]
        md2 = pattern_to_markdown(p2, bindings2)

        fm1 = yaml.safe_load(md1.split("---")[1])
        fm2 = yaml.safe_load(md2.split("---")[1])
        assert fm1["name"] == fm2["name"]
        assert fm1["tags"] == fm2["tags"]
        assert fm1["bindings"] == fm2["bindings"]


# ===========================================================================
# Hypothesis property-based tests
# ===========================================================================

if HYPOTHESIS_AVAILABLE:
    # Strategies for safe text (printable ASCII, no YAML special chars)
    _safe_text = st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters=" .-_",
        ),
        min_size=1,
        max_size=80,
    ).filter(lambda s: s.strip())

    _tag_strategy = st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-"),
            min_size=1,
            max_size=20,
        ).filter(lambda s: s.strip("-")),
        max_size=5,
    )

    _binding_type_strategy = st.sampled_from(VALID_BINDING_TYPES)

    _pattern_strategy = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="/*._-"),
        min_size=1,
        max_size=60,
    ).filter(lambda s: s.strip())

    _symbol_strategy = st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
            min_size=1,
            max_size=40,
        ).filter(lambda s: s.strip()),
    )

    @given(
        summary=_safe_text,
        tags=_tag_strategy,
        btype=_binding_type_strategy,
        file_pattern=_pattern_strategy,
        symbol=_symbol_strategy,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_hypothesis_decision_round_trip(
        summary: str,
        tags: List[str],
        btype: str,
        file_pattern: str,
        symbol: Optional[str],
    ) -> None:
        """Hypothesis: serialize Decision → parse → fields match."""
        d = _make_decision(summary=summary, tags=tags)
        b = _make_binding(btype, file_pattern, symbol=symbol)
        fm, _ = _write_and_parse_decision(d, [b])
        assert fm.uuid == d.uuid
        assert fm.title == summary
        assert fm.tags == tags
        assert len(fm.bindings) == 1
        assert fm.bindings[0].type == btype
        assert fm.bindings[0].pattern == file_pattern
        assert fm.bindings[0].symbol == symbol

    @given(
        name=_safe_text,
        tags=_tag_strategy,
        btype=_binding_type_strategy,
        file_pattern=_pattern_strategy,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_hypothesis_pattern_round_trip(
        name: str,
        tags: List[str],
        btype: str,
        file_pattern: str,
    ) -> None:
        """Hypothesis: serialize SystemPattern → parse → fields match."""
        p = _make_pattern(name=name, tags=tags)
        b = _make_binding(btype, file_pattern, item_type="system_pattern")
        fm, _ = _write_and_parse_pattern(p, [b])
        assert fm.name == name
        assert fm.tags == tags
        assert len(fm.bindings) == 1
        assert fm.bindings[0].type == btype

    @given(
        category=_safe_text,
        key=_safe_text,
        value=st.one_of(
            st.text(max_size=100),
            st.integers(),
            st.booleans(),
            st.none(),
            st.lists(st.integers(), max_size=5),
        ),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_hypothesis_shared_data_round_trip(
        category: str, key: str, value: Any
    ) -> None:
        """Hypothesis: serialize custom data → parse → value matches."""
        fm, parsed = _write_and_parse_shared_data(category, [(key, value)])
        assert fm.category == category
        assert parsed[key] == value

else:
    # Provide a placeholder so pytest doesn't complain about missing tests
    def test_hypothesis_skipped_no_hypothesis_installed() -> None:  # type: ignore[misc]
        pytest.skip("hypothesis not installed — install with pip install hypothesis")
