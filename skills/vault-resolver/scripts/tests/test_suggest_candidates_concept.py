"""
test_suggest_candidates_concept.py: tests for suggest_candidates.suggest()
with kind='concept', and for vault_io.get_existing_concept_names().

All tests use the `fake_vault` fixture (defined in conftest.py) so that no
real vault/ files are read.

Expected concept names in fake_vault:
  - AI研修方法論
  - 知識の構造化
  - tool-level-framework
  - api-reference
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# get_existing_concept_names
# ---------------------------------------------------------------------------
class TestGetExistingConceptNames:
    def test_finds_all_knowledge_notes(self, fake_vault):
        """All four knowledge notes in fake_vault are returned."""
        from lib.vault_io import get_existing_concept_names

        names = get_existing_concept_names()
        assert names == {"AI研修方法論", "知識の構造化", "tool-level-framework", "api-reference"}

    def test_excludes_index_and_readme(self, fake_vault, tmp_path):
        """index.md and README.md stems are excluded from results."""
        # Plant index files inside insights/
        import lib.vault_io as vault_io

        (vault_io.KNOWLEDGE_DIR / "insights" / "index.md").write_text("", encoding="utf-8")
        (vault_io.KNOWLEDGE_DIR / "insights" / "README.md").write_text("", encoding="utf-8")

        names = vault_io.get_existing_concept_names()
        assert "index" not in names
        assert "README" not in names


# ---------------------------------------------------------------------------
# suggest() with kind='concept'
# ---------------------------------------------------------------------------
class TestSuggestConcept:
    def test_concept_kind_returns_candidates_from_knowledge(self, fake_vault):
        """Fuzzy query for 'AI研修方法' should surface 'AI研修方法論'."""
        from suggest_candidates import suggest

        results = suggest(link="AI研修方法", kind="concept", top_n=3)
        assert len(results) > 0
        names = [r["name"] for r in results]
        assert "AI研修方法論" in names

    def test_concept_kind_exact_match_high_confidence(self, fake_vault):
        """Exact name 'AI研修方法論' should match with confidence >= 0.90."""
        from suggest_candidates import suggest

        results = suggest(link="AI研修方法論", kind="concept", top_n=3)
        assert len(results) > 0
        top = results[0]
        assert top["name"] == "AI研修方法論"
        assert top["confidence"] >= 0.90

    def test_unknown_kind_returns_empty_list(self, fake_vault):
        """kind='unknown' → empty list (no pool to search)."""
        from suggest_candidates import suggest

        results = suggest(link="何か", kind="unknown", top_n=3)
        assert results == []

    def test_concept_no_close_match_returns_empty(self, fake_vault):
        """A query completely unlike any existing concept → no candidates."""
        from suggest_candidates import suggest

        results = suggest(link="完全に違うトピック", kind="concept", top_n=3)
        # Either empty or every result has very low confidence (below 0.45)
        for r in results:
            assert r["confidence"] < 0.45, (
                f"Expected no high-confidence match but got {r}"
            )
