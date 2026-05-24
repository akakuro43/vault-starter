#!/usr/bin/env python3
"""
test_classify_project.py: classify_project.py の二段分類 (client → project)
の単体テスト。

検証観点:
  - company の name / aliases が title hit → client.confidence=high
  - body のみ hit → client.confidence=medium
  - client がマッチしたら projects は company.projects に絞り込まれる
  - 絞り込み後が空なら全件 fallback
  - client マッチなしなら全 project スコア
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# scripts/ を import パスに追加
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import vault_io  # noqa: E402
import classify_project as cp  # noqa: E402


# ── テスト用フィクスチャ生成 ─────────────────────────────────

def _setup_vault(tmp_path: Path, companies: list[dict], projects: list[dict]) -> None:
    """tmp_path に 03_companies/ と 01_projects/ を作る。"""
    comp_dir = tmp_path / "03_companies"
    proj_dir = tmp_path / "01_projects"
    comp_dir.mkdir(parents=True, exist_ok=True)
    proj_dir.mkdir(parents=True, exist_ok=True)

    for c in companies:
        slug = c["slug"]
        fm_lines = ["---", f"type: company", f"name: {c['name']}"]
        if c.get("aliases") is not None:
            fm_lines.append(f"aliases: {c['aliases']}")
        if c.get("projects") is not None:
            fm_lines.append("projects:")
            for p in c["projects"]:
                fm_lines.append(f'  - "[[{p}]]"')
        fm_lines.append("---\n")
        (comp_dir / f"{slug}.md").write_text("\n".join(fm_lines), encoding="utf-8")

    for p in projects:
        slug = p["slug"]
        d = proj_dir / slug
        d.mkdir(exist_ok=True)
        fm_lines = ["---", "type: project", f"name: {p['name']}"]
        if p.get("aliases"):
            fm_lines.append(f"aliases: {p['aliases']}")
        if p.get("keywords"):
            fm_lines.append(f"keywords: {p['keywords']}")
        if p.get("client"):
            fm_lines.append(f'client: "[[{p["client"]}]]"')
        fm_lines.append(f"status: {p.get('status', 'active')}")
        fm_lines.append("---\n")
        (d / f"{slug}.md").write_text("\n".join(fm_lines), encoding="utf-8")


def _make_transcript(tmp_path: Path, title: str, body: str = "") -> Path:
    path = tmp_path / "transcript.md"
    path.write_text(
        f"---\ntype: transcript\ndate: 2026-05-22\ntitle: \"{title}\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _patch_paths(tmp_path: Path):
    """vault_io のパス定数を tmp_path 配下に向ける context manager 生成器。"""
    return patch.multiple(
        vault_io,
        VAULT_DIR=tmp_path,
        COMPANIES_DIR=tmp_path / "03_companies",
        PROJECTS_DIR=tmp_path / "01_projects",
    )


# ── テストケース ────────────────────────────────────────────

class TestClientMatch:

    def test_title_hit_returns_high_confidence(self, tmp_path: Path):
        """company name が title に含まれていれば client.confidence=high。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "ゴダイ", "name": "ゴダイ", "projects": []}],
            projects=[],
        )
        transcript = _make_transcript(tmp_path, "【ゴダイ】岡正明さんMTG")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"] is not None
        assert result["client"]["slug"] == "ゴダイ"
        assert result["client"]["confidence"] == "high"
        assert any("title:" in v for v in result["client"]["matched_via"])

    def test_alias_hit_returns_high_confidence(self, tmp_path: Path):
        """aliases の値が title に含まれていれば high。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "ゴダイ", "name": "ゴダイ", "aliases": ["五代"], "projects": []}],
            projects=[],
        )
        transcript = _make_transcript(tmp_path, "五代AI研修 第3回")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"]["confidence"] == "high"
        assert "title:五代" in result["client"]["matched_via"]

    def test_body_only_hit_returns_medium(self, tmp_path: Path):
        """title に無く body にのみ含まれていれば medium。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "ゴダイ", "name": "ゴダイ", "projects": []}],
            projects=[],
        )
        transcript = _make_transcript(tmp_path, "定例会", body="ゴダイの研修について議論")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"]["confidence"] == "medium"
        assert "body:ゴダイ" in result["client"]["matched_via"]

    def test_no_hit_returns_null(self, tmp_path: Path):
        """company にヒットしなければ client=null。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "ゴダイ", "name": "ゴダイ", "projects": []}],
            projects=[],
        )
        transcript = _make_transcript(tmp_path, "別件のミーティング", body="他社の話")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"] is None


class TestProjectScoping:

    def test_client_filters_projects(self, tmp_path: Path):
        """client がマッチしたら projects はその company.projects に絞られる。"""
        _setup_vault(
            tmp_path,
            companies=[{
                "slug": "ゴダイ",
                "name": "ゴダイ",
                "projects": ["godai-ai-training"],
            }],
            projects=[
                {"slug": "godai-ai-training", "name": "ゴダイ AI研修",
                 "aliases": ["ゴダイ研修"], "client": "ゴダイ"},
                {"slug": "other-project", "name": "他社案件",
                 "aliases": ["他社"], "client": "別会社"},
            ],
        )
        transcript = _make_transcript(tmp_path, "【ゴダイ】岡正明さんMTG")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"]["slug"] == "ゴダイ"
        # projects には godai-ai-training のみ（other-project は除外）
        slugs = [p["project"] for p in result["projects"]]
        assert "other-project" not in slugs
        # scope は client-filtered
        for p in result["projects"]:
            assert p["scope"] == "client-filtered"

    def test_no_client_match_scores_all_projects(self, tmp_path: Path):
        """client マッチがなければ全 project スコア（scope=all）。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "ゴダイ", "name": "ゴダイ", "projects": []}],
            projects=[
                {"slug": "other-project", "name": "他社案件",
                 "aliases": ["他社"], "client": "別会社"},
            ],
        )
        transcript = _make_transcript(tmp_path, "他社との打ち合わせ")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"] is None
        if result["projects"]:
            for p in result["projects"]:
                assert p["scope"] == "all"

    def test_empty_company_projects_falls_back_to_all(self, tmp_path: Path):
        """company.projects: [] なら全件 fallback。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "ゴダイ", "name": "ゴダイ", "projects": []}],
            projects=[
                {"slug": "godai-ai-training", "name": "ゴダイ AI研修",
                 "aliases": ["ゴダイ研修"], "client": "ゴダイ"},
            ],
        )
        transcript = _make_transcript(tmp_path, "ゴダイ研修の話")

        with _patch_paths(tmp_path):
            result = cp.classify(transcript)

        assert result["client"]["slug"] == "ゴダイ"
        # company.projects が空でも、全件スコアで godai-ai-training がヒット
        for p in result["projects"]:
            assert p["scope"] == "all"


class TestLoadCompanies:

    def test_name_is_implicit_alias(self, tmp_path: Path):
        """aliases フィールドが無くても name が _aliases に含まれる。"""
        _setup_vault(
            tmp_path,
            companies=[{"slug": "Xenkai", "name": "Xenkai", "projects": []}],
            projects=[],
        )
        with _patch_paths(tmp_path):
            companies = vault_io.load_companies()

        assert len(companies) == 1
        assert "Xenkai" in companies[0]["_aliases"]

    def test_name_and_aliases_merged_dedup(self, tmp_path: Path):
        """name と aliases が重複していても重複排除される。"""
        _setup_vault(
            tmp_path,
            companies=[{
                "slug": "ゴダイ", "name": "ゴダイ",
                "aliases": ["ゴダイ", "五代", "五大"],  # 先頭は name と重複
                "projects": [],
            }],
            projects=[],
        )
        with _patch_paths(tmp_path):
            companies = vault_io.load_companies()

        aliases = companies[0]["_aliases"]
        assert aliases.count("ゴダイ") == 1
        assert "五代" in aliases
        assert "五大" in aliases
