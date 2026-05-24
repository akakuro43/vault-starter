#!/usr/bin/env python3
"""
test_create_tasks_from_actions_owner.py: create_tasks_from_actions.py の owner 推論機能に関する単体テスト。

T0129 Step 3 のテスト実装。
対象: owner inferences JSON の読み込み、owner=other のスキップ、
      owner=endo/unclear の起票、content 不一致時の WARN、冪等性ガード等。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

# スクリプトディレクトリを import パスに追加
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import create_tasks_from_actions as cta  # noqa: E402


# ── フィクスチャファイルパス ───────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MEETING_FIXTURE = FIXTURES_DIR / "meeting_with_action_items.md"
OWNER_INFERENCES_FIXTURE = FIXTURES_DIR / "owner_inferences_sample.json"


# ── テスト用 action items（extract_action_items.py の出力を模倣） ─────────────

# 議事録 fixture から抽出される action items（手動で構築）
# content は extract_action_items.py の regex パース結果に合わせる（strip 済み）
SAMPLE_ACTION_ITEMS = [
    {
        "line_no": 24,
        "content": "AtomicFlow の API 仕様書を作成する",
        "assignee_raw": "遠藤雅俊",
        "assignee_resolved": None,
        "due": "2026-05-20",
        "raw_line": "- [ ] AtomicFlow の API 仕様書を作成する — 担当: [[遠藤雅俊]] / 期限: 2026-05-20",
    },
    {
        "line_no": 25,
        "content": "デプロイ手順書を確認して山田さんに共有する",
        "assignee_raw": "山田太郎",
        "assignee_resolved": None,
        "due": None,
        "raw_line": "- [ ] デプロイ手順書を確認して山田さんに共有する — 担当: [[山田太郎]]",
    },
    {
        "line_no": 26,
        "content": "競合サービスの調査レポートをまとめる",
        "assignee_raw": None,
        "assignee_resolved": None,
        "due": "2026-05-22",
        "raw_line": "- [ ] 競合サービスの調査レポートをまとめる / 期限: 2026-05-22",
    },
    {
        "line_no": 27,
        "content": "次回 MTG のアジェンダを送付する",
        "assignee_raw": None,
        "assignee_resolved": None,
        "due": None,
        "raw_line": "- [ ] 次回 MTG のアジェンダを送付する",
    },
    {
        "line_no": 28,
        "content": "クライアント向け提案書を作成する",
        "assignee_raw": "遠藤雅俊",
        "assignee_resolved": None,
        "due": "2026-05-25",
        "raw_line": "- [ ] クライアント向け提案書を作成する — 担当: [[遠藤雅俊]] / 期限: 2026-05-25",
    },
]

# owner_inferences_sample.json の内容（fixture ファイルと同期）
SAMPLE_OWNER_INFERENCES_LIST = json.loads(OWNER_INFERENCES_FIXTURE.read_text(encoding="utf-8"))


def _make_owner_inferences_map(items: list[dict]) -> dict[str, dict]:
    """owner inferences リストから item_content キーの dict を構築する。"""
    return {entry["item_content"].strip(): entry for entry in items if isinstance(entry, dict)}


def _make_meeting_md(tmp_path: Path, extra_frontmatter: str = "") -> Path:
    """テスト用の最小議事録ファイルを tmp_path に作成して返す。

    extra_frontmatter に追加の frontmatter フィールドを渡せる（例: tasks_extracted_at）。
    textwrap.dedent との干渉を避けるため、文字列連結で frontmatter を構築する。
    """
    fm_extra_block = f"\n{extra_frontmatter.strip()}" if extra_frontmatter.strip() else ""
    content = (
        "---\n"
        "date: 2026-05-15\n"
        "title: テスト用合成議事録\n"
        'project: "[[test-project]]"\n'
        + fm_extra_block
        + "\n---\n"
        "\n"
        "# テスト用合成議事録\n"
        "\n"
        "## ネクストアクション\n"
        "\n"
        "- [ ] AtomicFlow の API 仕様書を作成する — 担当: [[遠藤雅俊]] / 期限: 2026-05-20\n"
        "- [ ] デプロイ手順書を確認して山田さんに共有する — 担当: [[山田太郎]]\n"
        "- [ ] 競合サービスの調査レポートをまとめる / 期限: 2026-05-22\n"
        "- [ ] 次回 MTG のアジェンダを送付する\n"
        "- [ ] クライアント向け提案書を作成する — 担当: [[遠藤雅俊]] / 期限: 2026-05-25\n"
    )
    meeting_path = tmp_path / "2026-05-15-test-meeting.md"
    meeting_path.write_text(content, encoding="utf-8")
    return meeting_path


def _run_process(
    tmp_path: Path,
    action_items: list[dict],
    owner_inferences: Optional[dict[str, dict]] = None,
    dry_run: bool = True,
    extra_frontmatter: str = "",
) -> dict:
    """TASKS_DIR / VAULT_DIR を tmp_path にモンキーパッチして process() を実行する。

    実 vault ファイルへの副作用を完全に防ぐ。
    """
    meeting_path = _make_meeting_md(tmp_path, extra_frontmatter=extra_frontmatter)

    tasks_dir = tmp_path / "05_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    people_dir = tmp_path / "02_people"
    people_dir.mkdir(parents=True, exist_ok=True)

    # VAULT_DIR / TASKS_DIR / PEOPLE_DIR をすべて tmp_path 配下にリダイレクト
    with (
        patch.object(cta, "VAULT_DIR", tmp_path),
        patch.object(cta, "TASKS_DIR", tasks_dir),
        patch.object(cta, "PEOPLE_DIR", people_dir),
    ):
        result = cta.process(
            meeting_path=meeting_path,
            action_items=action_items,
            dry_run=dry_run,
            owner_inferences=owner_inferences,
        )

    return result


# ── ケース 1: owner=endo → タスク起票 + 「## 概要」差し込み ─────────────────

class TestOwnerEndo:
    """対応受け入れ基準: §1.2-4"""

    def test_endo_task_created_with_gaiyou_section(self, tmp_path: Path) -> None:
        """owner=endo → タスクが起票され「## 概要」に prerequisites/completion_criteria が差し込まれる。

        対応受け入れ基準: §1.2-4
        """
        # owner=endo のアイテムのみを含む action_items と inferences
        action_items = [SAMPLE_ACTION_ITEMS[0]]  # "AtomicFlow の API 仕様書を作成する"
        inference_entry = SAMPLE_OWNER_INFERENCES_LIST[0]  # owner=endo
        assert inference_entry["owner"] == "endo"

        owner_inferences = _make_owner_inferences_map([inference_entry])

        # 実ファイルを書き込む（dry_run=False）で確認する
        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=owner_inferences,
            dry_run=False,
        )

        # 1 件起票されること
        assert len(result["created"]) == 1, f"created が 1 件でない: {result}"
        assert result["skipped"] == []

        # タスクファイルが生成されていること
        tasks_dir = tmp_path / "05_tasks"
        task_files = list(tasks_dir.glob("T*.md"))
        assert len(task_files) == 1, f"タスクファイルが 1 件でない: {task_files}"

        task_content = task_files[0].read_text(encoding="utf-8")

        # 「## 概要」セクションに「### 前提」と「### 完了条件」が差し込まれていること
        assert "### 前提" in task_content, "### 前提 が見つからない"
        assert "### 完了条件" in task_content, "### 完了条件 が見つからない"

        # prerequisites の内容が含まれていること
        assert "AtomicFlow の現行 API 構成を把握していること" in task_content

        # フッターが含まれていること（spec §5.2.4）
        assert "/plan-task` 実行時に spec.md ベースの要約で上書きされます" in task_content

        # 現行プレースホルダが残っていないこと
        assert "// /plan-task で記入されます" not in task_content


# ── ケース 2: owner=other → 起票スキップ、逆リンクなし、skipped に記録 ────

class TestOwnerOther:
    """対応受け入れ基準: §1.2-2, §1.2-3"""

    def test_other_task_skipped_and_no_reverse_link(self, tmp_path: Path) -> None:
        """owner=other → タスク起票スキップ、議事録行に逆リンクなし、skipped 配列に記録。

        対応受け入れ基準: §1.2-2, §1.2-3
        """
        action_items = [SAMPLE_ACTION_ITEMS[1]]  # "デプロイ手順書を確認して山田さんに共有する"
        inference_entry = SAMPLE_OWNER_INFERENCES_LIST[1]  # owner=other
        assert inference_entry["owner"] == "other"

        owner_inferences = _make_owner_inferences_map([inference_entry])

        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=owner_inferences,
            dry_run=False,
        )

        # 起票されていないこと
        assert result["created"] == [], f"other なのに起票された: {result['created']}"

        # skipped 配列に記録されていること
        assert len(result["skipped"]) == 1
        skipped = result["skipped"][0]
        assert skipped["owner"] == "other"
        assert skipped["reason"] == "agent_inferred_other"
        assert "デプロイ手順書を確認して山田さんに共有する" in skipped["content"]

        # タスクファイルが作成されていないこと
        tasks_dir = tmp_path / "05_tasks"
        task_files = list(tasks_dir.glob("T*.md"))
        assert task_files == [], f"other なのにタスクファイルが作成された: {task_files}"

        # 議事録のターゲット行に逆リンク「→ [[T####]]」が付いていないこと
        meeting_files = list(tmp_path.glob("*.md"))
        assert len(meeting_files) == 1
        meeting_content = meeting_files[0].read_text(encoding="utf-8")
        # owner=other の行（デプロイ手順書）には → [[T が付いていないこと
        for line in meeting_content.split("\n"):
            if "デプロイ手順書を確認して山田さんに共有する" in line:
                assert "→ [[T" not in line, f"逆リンクが付いてしまっている: {line!r}"


# ── ケース 3: owner=unclear → タスク起票（endo と同等、## 概要差し込みあり） ─

class TestOwnerUnclear:
    """対応受け入れ基準: §1.2-4"""

    def test_unclear_task_created_with_gaiyou_section(self, tmp_path: Path) -> None:
        """owner=unclear → タスクが起票され「## 概要」に前提・完了条件が差し込まれる。

        対応受け入れ基準: §1.2-4
        """
        action_items = [SAMPLE_ACTION_ITEMS[2]]  # "競合サービスの調査レポートをまとめる"
        inference_entry = SAMPLE_OWNER_INFERENCES_LIST[2]  # owner=unclear
        assert inference_entry["owner"] == "unclear"

        owner_inferences = _make_owner_inferences_map([inference_entry])

        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=owner_inferences,
            dry_run=False,
        )

        # 1 件起票されること
        assert len(result["created"]) == 1, f"unclear なのに起票されなかった: {result}"
        assert result["skipped"] == []

        # タスクファイルに「### 前提」と「### 完了条件」が含まれていること
        tasks_dir = tmp_path / "05_tasks"
        task_files = list(tasks_dir.glob("T*.md"))
        assert len(task_files) == 1
        task_content = task_files[0].read_text(encoding="utf-8")

        assert "### 前提" in task_content
        assert "### 完了条件" in task_content
        assert "対象競合サービスのリストが確定していること" in task_content
        assert "/plan-task` 実行時に spec.md ベースの要約で上書きされます" in task_content


# ── ケース 4: item_content 不一致 → 現行挙動（全件起票）、WARN と mismatch_count ─

class TestContentMismatch:
    """対応受け入れ基準: §1.2-7（互換性）"""

    def test_mismatch_falls_back_to_default_and_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """owner_inferences の item_content が不一致 → 現行挙動（起票）、content_mismatch_count>0、stderr WARN。

        対応受け入れ基準: §1.2-7（互換性）
        """
        action_items = [SAMPLE_ACTION_ITEMS[3]]  # "次回 MTG のアジェンダを送付する"
        # fixture の item 3（index=3）は "この内容は議事録に存在しないため..." → ミスマッチ
        mismatch_inference = SAMPLE_OWNER_INFERENCES_LIST[3]
        assert "ミスマッチ" in mismatch_inference["item_content"]

        # inference map に action item の content とは一致しないキーを入れる
        owner_inferences = _make_owner_inferences_map([mismatch_inference])

        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=owner_inferences,
            dry_run=True,  # dry_run で副作用なし
        )

        # 不一致のためフォールバック → 現行挙動（起票される）
        assert len(result["created"]) == 1, f"フォールバックで起票されるはず: {result}"

        # content_mismatch_count が 1 以上であること
        assert result["content_mismatch_count"] > 0, "content_mismatch_count が 0"

        # mismatches リストに記録されていること
        assert len(result["mismatches"]) > 0

        # stderr に [WARN] が出力されていること
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err, f"stderr に [WARN] がない: {captured.err!r}"
        assert "owner_inferences の item_content がマッチしません" in captured.err


# ── ケース 5: owner_inferences が空配列 → 全件起票（現行挙動、互換性確保） ──

class TestEmptyOwnerInferences:
    """対応受け入れ基準: §1.2-7（互換性）"""

    def test_empty_inferences_creates_all_tasks(self, tmp_path: Path) -> None:
        """owner_inferences が空配列 → 全件 skip ではなく現行挙動（全件起票）。

        対応受け入れ基準: §1.2-7（互換性）
        """
        action_items = SAMPLE_ACTION_ITEMS[:3]  # 3 件

        # 空配列 → _load_owner_inferences が空 dict → use_owner_inferences=False
        owner_inferences: dict[str, dict] = {}  # 空配列から構築した空 dict

        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=owner_inferences,  # 空 dict = 未指定と同等
            dry_run=True,
        )

        # 全 3 件起票されること
        assert len(result["created"]) == 3, f"全件起票されるはず: {result}"
        assert result["skipped"] == []
        assert result["content_mismatch_count"] == 0

    def test_load_owner_inferences_empty_list(self, tmp_path: Path) -> None:
        """_load_owner_inferences に空配列の JSON ファイルを渡すと空 dict が返る。

        対応受け入れ基準: §1.2-7（互換性）
        """
        empty_json_path = tmp_path / "empty_inferences.json"
        empty_json_path.write_text("[]", encoding="utf-8")

        result = cta._load_owner_inferences(str(empty_json_path))

        assert result == {}, f"空配列から空 dict が返るはず: {result}"


# ── ケース 6: --owner-inferences 未指定 → T0116 互換（全件起票、現行挙動） ──

class TestNoOwnerInferences:
    """対応受け入れ基準: §1.2-7（互換性）"""

    def test_no_inferences_creates_all_tasks(self, tmp_path: Path) -> None:
        """--owner-inferences 未指定（None）→ 全件起票（T0116 と同等挙動）。

        対応受け入れ基準: §1.2-7（互換性）
        """
        action_items = SAMPLE_ACTION_ITEMS  # 全 5 件

        # owner_inferences=None で process() を呼ぶ（--owner-inferences 未指定と同等）
        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=None,
            dry_run=True,
        )

        # 全 5 件起票されること（owner=other でもスキップされない）
        assert len(result["created"]) == 5, f"全 5 件起票されるはず: {result}"
        assert result["skipped"] == []
        assert result["content_mismatch_count"] == 0

    def test_no_inferences_no_gaiyou_injection(self, tmp_path: Path) -> None:
        """--owner-inferences 未指定時は「## 概要」にプレースホルダが維持される。

        対応受け入れ基準: §1.2-7（互換性）
        """
        action_items = [SAMPLE_ACTION_ITEMS[0]]

        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=None,
            dry_run=False,
        )

        assert len(result["created"]) == 1

        tasks_dir = tmp_path / "05_tasks"
        task_files = list(tasks_dir.glob("T*.md"))
        assert len(task_files) == 1
        task_content = task_files[0].read_text(encoding="utf-8")

        # 現行プレースホルダが維持されていること
        assert "// /plan-task で記入されます" in task_content
        # owner 推論由来のセクションが入っていないこと
        assert "### 前提" not in task_content
        assert "### 完了条件" not in task_content


# ── ケース 7: tasks_extracted_at 済み議事録 → 何も起票しない（冪等性） ────────

class TestIdempotency:
    """対応受け入れ基準: §1.2-5, §1.2-6"""

    def test_already_extracted_meeting_is_skipped(self, tmp_path: Path) -> None:
        """tasks_extracted_at 済み議事録に再実行 → 何も起票しない。

        対応受け入れ基準: §1.2-5, §1.2-6
        """
        action_items = SAMPLE_ACTION_ITEMS
        owner_inferences = _make_owner_inferences_map(SAMPLE_OWNER_INFERENCES_LIST)

        # tasks_extracted_at が設定済みの議事録
        result = _run_process(
            tmp_path,
            action_items=action_items,
            owner_inferences=owner_inferences,
            dry_run=False,
            extra_frontmatter="tasks_extracted_at: 2026-05-14T09:00:00+09:00",
        )

        # 冪等性ガード: 何も起票されない
        assert result["created"] == [], f"already_extracted なのに起票された: {result}"
        assert result["failed"] == []
        assert result["skipped_reason"] == "already_extracted"

        # タスクファイルが作成されていないこと
        tasks_dir = tmp_path / "05_tasks"
        task_files = list(tasks_dir.glob("T*.md"))
        assert task_files == [], f"タスクファイルが作成されてしまった: {task_files}"


# ── ケース 8: _build_task_content() 単体 — prerequisites=None / criteria=None ─

class TestBuildTaskContentUnit:
    """対応受け入れ基準: §1.2-4"""

    def test_both_none_keeps_placeholder(self) -> None:
        """prerequisites=None / completion_criteria=None → 現行プレースホルダ「// /plan-task で記入されます」を維持。

        対応受け入れ基準: §1.2-4
        """
        content = cta._build_task_content(
            task_id="T9999",
            slug="test-task",
            title="テストタスク",
            task_type="admin",
            priority="P2",
            assignee="[[遠藤雅俊]]",
            project=None,
            related_meeting_stem="2026-05-15-test",
            created="2026-05-15",
            due=None,
            raw_line="- [ ] テストタスク",
            prerequisites=None,
            completion_criteria=None,
        )

        assert "// /plan-task で記入されます" in content
        assert "### 前提" not in content
        assert "### 完了条件" not in content
        assert "上書きされます" not in content

    def test_prerequisites_only_injects_section(self) -> None:
        """prerequisites のみ提供 → 「### 前提」が差し込まれ、フッターが追加される。

        対応受け入れ基準: §1.2-4
        """
        content = cta._build_task_content(
            task_id="T9999",
            slug="test-task",
            title="テストタスク",
            task_type="admin",
            priority="P2",
            assignee="[[遠藤雅俊]]",
            project=None,
            related_meeting_stem="2026-05-15-test",
            created="2026-05-15",
            due=None,
            raw_line="- [ ] テストタスク",
            prerequisites="- テスト前提条件",
            completion_criteria=None,
        )

        assert "### 前提" in content
        assert "テスト前提条件" in content
        assert "### 完了条件" not in content
        assert "/plan-task` 実行時に spec.md ベースの要約で上書きされます" in content
        assert "// /plan-task で記入されます" not in content

    def test_both_provided_injects_full_section(self) -> None:
        """prerequisites / completion_criteria 両方提供 → 両方差し込み + フッター。

        対応受け入れ基準: §1.2-4
        """
        content = cta._build_task_content(
            task_id="T9999",
            slug="test-task",
            title="テストタスク",
            task_type="admin",
            priority="P2",
            assignee="[[遠藤雅俊]]",
            project=None,
            related_meeting_stem="2026-05-15-test",
            created="2026-05-15",
            due=None,
            raw_line="- [ ] テストタスク",
            prerequisites="- テスト前提A\n- テスト前提B",
            completion_criteria="- [ ] 完了条件1\n- [ ] 完了条件2",
        )

        assert "### 前提" in content
        assert "テスト前提A" in content
        assert "### 完了条件" in content
        assert "完了条件1" in content
        assert "/plan-task` 実行時に spec.md ベースの要約で上書きされます" in content
        assert "// /plan-task で記入されます" not in content
