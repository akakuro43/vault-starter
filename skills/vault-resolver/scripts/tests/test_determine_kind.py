"""
test_determine_kind.py: unit tests for scan_unresolved.determine_kind().

Tests cover the 3-layer classification logic:
  Layer 1 – strong string patterns (path, meeting)
  Layer 2 – field context voting (person, project, concept)
  Layer 3 – weak patterns (project slug, concept suffix, unknown)

Regression test: Japanese text without a field context must NOT return 'person'.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scan_unresolved import determine_kind


# ---------------------------------------------------------------------------
# Helper: build an appearances list with the given context field
# ---------------------------------------------------------------------------
def _appearances(*contexts: str) -> list[dict]:
    """Return a list of appearance dicts with the given context values."""
    return [{"file": "dummy.md", "line": 1, "context": ctx} for ctx in contexts]


# ---------------------------------------------------------------------------
# Layer 1 tests: strong string patterns
# ---------------------------------------------------------------------------
class TestLayer1Strong:
    def test_path_with_slash(self):
        """'/' in link → 'path', no matter the appearances."""
        result = determine_kind("01_projects/foo/foo", _appearances("body"))
        assert result == "path"

    def test_meeting_date_prefix(self):
        """YYYY-MM-DD prefix → 'meeting'."""
        result = determine_kind("2026-05-21 朝会", _appearances("body"))
        assert result == "meeting"

    def test_meeting_suffix(self):
        """Link ending with 'ミーティング' → 'meeting'."""
        result = determine_kind("週次定例ミーティング", _appearances("body"))
        assert result == "meeting"


# ---------------------------------------------------------------------------
# Layer 2 tests: field context voting
# ---------------------------------------------------------------------------
class TestLayer2FieldContext:
    def test_person_via_participants_field(self):
        """Link appearing in 'participants' field → 'person'."""
        result = determine_kind("山田太郎", _appearances("participants"))
        assert result == "person"

    def test_project_via_project_field(self):
        """Link appearing in 'project' field → 'project'."""
        result = determine_kind("foo-project", _appearances("project"))
        assert result == "project"

    def test_concept_via_concept_field(self):
        """Link in 'concept' field → 'concept'."""
        result = determine_kind("ナレッジ統合", _appearances("concept"))
        assert result == "concept"

    def test_field_majority_wins(self):
        """When multiple appearances differ, the majority context wins."""
        # 2 × participants vs 1 × project → person
        apps = _appearances("participants", "participants", "project")
        result = determine_kind("田中花子", apps)
        assert result == "person"


# ---------------------------------------------------------------------------
# Layer 3 tests: weak fallback patterns
# ---------------------------------------------------------------------------
class TestLayer3WeakPattern:
    @pytest.mark.parametrize("link,expected_kind", [
        ("新規事業戦略", "concept"),
        ("AI研修方法論", "concept"),
    ])
    def test_concept_via_suffix(self, link, expected_kind):
        """Japanese link with a concept-suffix (戦略/方法論) → 'concept'."""
        result = determine_kind(link, _appearances("body"))
        assert result == expected_kind

    def test_project_via_ascii_slug(self):
        """Pure ASCII slug with no field context → 'project'."""
        result = determine_kind("my-cool-project", _appearances("body"))
        assert result == "project"

    def test_unknown_japanese_no_suffix_no_field(self):
        """
        Regression: Japanese text with no concept suffix and no field context
        must NOT return 'person'.  Old bug: 'Japanese text = person'.
        """
        result = determine_kind("ふわっとした単語", _appearances("body"))
        assert result == "unknown"
        assert result != "person"

    def test_unknown_empty_appearances(self):
        """No appearances at all → 'unknown'."""
        result = determine_kind("ふわっとした単語", [])
        assert result == "unknown"
