#!/usr/bin/env python3
"""
create_tasks_from_actions.py: extract_action_items.py の出力 (JSON) を受け取り、
各 action item から vault/05_tasks/T####-<slug>.md を生成する。

議事録側に逆リンク（行末 → [[T####-<slug>]] と ## 派生タスク セクション）を追記し、
frontmatter に tasks_extracted_at を記録する（冪等性）。

タスクカードのフォーマット詳細は同スキルの SKILL.md を参照。

Usage:
  python3 create_tasks_from_actions.py \
    --meeting <meeting-md-path> \
    --action-items <json-path or - for stdin> \
    [--owner-inferences <json-path or - for stdin>] \
    [--dry-run] [--pretty]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── パス定数 ──────────────────────────────────────────────────────────────────
# VAULT_PATH 環境変数で上書き可。デフォルトはリポジトリ直下の vault/
VAULT_DIR = Path(os.environ.get('VAULT_PATH', Path(__file__).resolve().parents[3] / 'vault')).expanduser().resolve()
TASKS_DIR = VAULT_DIR / "05_tasks"
PEOPLE_DIR = VAULT_DIR / "02_people"

# JST タイムゾーン
JST = timezone(timedelta(hours=9))

# ── 正規表現 ──────────────────────────────────────────────────────────────────

# frontmatter 区切り
_FRONTMATTER_BLOCK_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)

# frontmatter 内のフィールド1行（scalar のみ）
_FM_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*)$")

# ファイル名から ID を抽出（例: T0115-foo.md → T0115）
_FILENAME_ID_RE = re.compile(r"^(T\d{4}[a-z]?)-")

# frontmatter の id: フィールド
_FRONTMATTER_ID_RE = re.compile(r"^id:\s+(T\d{4}[a-z]?)\s*$", re.MULTILINE)

# 既にタスクリンクが行末に付いているか（冪等性チェック）
_ALREADY_LINKED_RE = re.compile(r"→\s*\[\[T\d{4}")

# 日付文字列（YAML frontmatter 内で引用符なし）
_DATE_VALUE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})$")

# ── type 推論キーワード ────────────────────────────────────────────────────────

_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "engineering",
        [
            "実装", "fix", "deploy", "skill", "スクリプト", "API", "DB",
            "frontend", "backend", "コード", "開発", "リファクタ", "テスト", "修正",
            "バグ", "インフラ", "セットアップ", "設計", "アーキテクチャ",
        ],
    ),
    (
        "communication",
        [
            "返信", "連絡", "メール", "送付", "スケジュール", "共有", "アナウンス",
            "通知", "報告", "MTG", "ミーティング", "打ち合わせ", "すり合わせ",
        ],
    ),
    (
        "research",
        [
            "調査", "比較", "分析", "検討", "リサーチ", "調べ", "確認", "評価",
            "検証", "レビュー",
        ],
    ),
    (
        "client",
        [
            "提案書", "研修", "資料作成", "クライアント", "LP", "カリキュラム",
            "プレゼン", "提案", "案件",
        ],
    ),
]

# ── priority 推論キーワード ────────────────────────────────────────────────────

_PRIORITY_P0_KEYWORDS = ["急ぎ", "至急", "今日中", "ASAP", "緊急"]
_PRIORITY_P1_KEYWORDS = ["来週", "今月中", "今週中"]


# ── path traversal 対策 ────────────────────────────────────────────────────────

def _is_within_vault(path: Path) -> bool:
    """path が VAULT_DIR 配下にあるか確認（symlink 解決後）。"""
    try:
        resolved = path.resolve()
        vault_resolved = VAULT_DIR.resolve()
        return (
            str(resolved).startswith(str(vault_resolved) + os.sep)
            or str(resolved) == str(vault_resolved)
        )
    except (OSError, RuntimeError):
        return False


# ── owner inferences 読み込み ────────────────────────────────────────────────

def _load_owner_inferences(json_path_or_stdin: Optional[str]) -> dict[str, dict]:
    """owner_inferences JSON を読み込み、item_content (strip 済み) をキーとした dict を返す。

    None / 未指定なら空 dict を返す（フォールバック路線）。
    JSON は以下のスキーマを想定:
    [
      {"item_content": "...", "owner": "endo|other|unclear",
       "purpose": "Markdown", "premise": "Markdown",
       "acceptance_criteria": "Markdown",
       "reasoning": "..."}
    ]
    """
    if json_path_or_stdin is None:
        return {}

    if json_path_or_stdin == "-":
        try:
            raw_json = sys.stdin.read()
        except KeyboardInterrupt:
            return {}
    else:
        inferences_path = Path(json_path_or_stdin).expanduser().resolve()
        if not inferences_path.exists():
            print(
                f"[ERROR] owner_inferences JSON が見つかりません: {inferences_path}",
                file=sys.stderr,
            )
            return {}
        try:
            raw_json = inferences_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[ERROR] owner_inferences JSON 読み込み失敗: {e}", file=sys.stderr)
            return {}

    try:
        data: list[dict] = json.loads(raw_json)
    except json.JSONDecodeError as e:
        print(f"[ERROR] owner_inferences JSON パース失敗: {e}", file=sys.stderr)
        return {}

    if not isinstance(data, list):
        print("[ERROR] owner_inferences は JSON 配列である必要があります", file=sys.stderr)
        return {}

    # item_content を .strip() してキー化した dict を構築
    result: dict[str, dict] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        item_content = entry.get("item_content", "")
        if isinstance(item_content, str):
            result[item_content.strip()] = entry
    return result


# ── frontmatter 操作（YAML パーサ不使用）────────────────────────────────────

def _extract_fm_text(content: str) -> Optional[tuple[str, str, int, int]]:
    """content から frontmatter テキストを抽出する。

    Returns:
        (fm_text, body, fm_start, fm_end) または None
        fm_start/fm_end は content 内の frontmatter テキスト（--- の内側）の位置
    """
    m = _FRONTMATTER_BLOCK_RE.match(content)
    if not m:
        return None
    fm_text = m.group(1)
    body = content[m.end():]
    return fm_text, body, m.start(1), m.end(1)


def _read_fm_field(content: str, key: str) -> Optional[str]:
    """frontmatter から単一スカラーフィールドの値を文字列で返す。

    wikilink の引用符（"[[...]]" → [[...]]）を除去して返す。
    見つからなければ None。
    """
    result = _extract_fm_text(content)
    if not result:
        return None
    fm_text = result[0]
    for line in fm_text.split("\n"):
        m = _FM_FIELD_RE.match(line.strip())
        if m and m.group("key") == key:
            val = m.group("value").strip().strip('"').strip("'")
            return val if val else None
    return None


def _fm_field_exists(content: str, key: str) -> bool:
    """frontmatter に key フィールドが存在するか確認。"""
    result = _extract_fm_text(content)
    if not result:
        return False
    fm_text = result[0]
    for line in fm_text.split("\n"):
        m = _FM_FIELD_RE.match(line.strip())
        if m and m.group("key") == key:
            return True
    return False


def _update_fm_field(content: str, key: str, new_value: str) -> str:
    """frontmatter の単一スカラーフィールドを書き換える（surgical regex）。

    フィールドが存在しない場合は末尾に追加する。
    """
    result = _extract_fm_text(content)
    if not result:
        raise ValueError("no frontmatter found")

    fm_text, body, fm_start, fm_end = result

    line_re = re.compile(rf"^({re.escape(key)}\s*:)([^\n]*)$", re.MULTILINE)
    line_m = line_re.search(fm_text)

    if line_m:
        # 複雑構造（次行がインデント）チェック
        rest = fm_text[line_m.end():]
        next_line = rest.lstrip("\n").split("\n", 1)[0] if rest else ""
        if next_line.startswith((" ", "\t", "-")):
            raise ValueError(
                f"field {key!r} appears to be a complex structure; refusing to update"
            )
        new_fm = fm_text[: line_m.start()] + f"{key}: {new_value}" + fm_text[line_m.end():]
    else:
        sep = "" if fm_text.endswith("\n") else "\n"
        new_fm = f"{fm_text}{sep}{key}: {new_value}"

    return content[:fm_start] + new_fm + content[fm_end:]


# ── ID 採番 ────────────────────────────────────────────────────────────────────

def _collect_all_ids() -> set[int]:
    """ファイル名と frontmatter の id: フィールド両方から既存 ID の数値セットを返す。"""
    ids: set[int] = set()

    for pattern in [TASKS_DIR.glob("T*.md"), TASKS_DIR.glob("archive/**/T*.md")]:
        try:
            for p in pattern:
                # ファイル名から
                m = _FILENAME_ID_RE.match(p.name)
                if m:
                    try:
                        num = int(m.group(1)[1:])  # "T0115" → 115
                        ids.add(num)
                    except ValueError:
                        pass
                # frontmatter から
                try:
                    text = p.read_text(encoding="utf-8")
                    fm_m = _FRONTMATTER_ID_RE.search(text)
                    if fm_m:
                        try:
                            num = int(fm_m.group(1)[1:5])  # "T0115" → 115
                            ids.add(num)
                        except ValueError:
                            pass
                except OSError:
                    pass
        except (OSError, StopIteration):
            pass

    return ids


def _next_task_id() -> str:
    """次の未使用タスク ID を T#### 形式で返す。"""
    ids = _collect_all_ids()
    if not ids:
        return "T0001"
    return f"T{max(ids) + 1:04d}"


def _id_is_free(task_id: str) -> bool:
    """task_id が未使用であることを確認（ファイル名 + frontmatter 両方チェック）。"""
    # ファイル名チェック
    existing = list(TASKS_DIR.glob(f"{task_id}-*.md"))
    if existing:
        return False

    # frontmatter チェック
    for p in TASKS_DIR.glob("T*.md"):
        try:
            text = p.read_text(encoding="utf-8")
            if _FRONTMATTER_ID_RE.search(text):
                # 既存ファイルの id: と比較
                m = _FRONTMATTER_ID_RE.search(text)
                if m and m.group(1) == task_id:
                    return False
        except OSError:
            pass

    return True


def _allocate_id(max_retries: int = 3, reserved_ids: Optional[set] = None) -> str:
    """ID を採番する。Write 直前の再確認付き（最大 max_retries 回）。

    Args:
        max_retries:  最大リトライ回数
        reserved_ids: 同一セッション内で仮予約済みの ID セット（dry-run / 連続採番用）
    """
    base_nums = _collect_all_ids()
    reserved_nums: set[int] = set()
    if reserved_ids:
        for rid in reserved_ids:
            if rid.startswith("T") and len(rid) >= 5:
                try:
                    reserved_nums.add(int(rid[1:5]))
                except ValueError:
                    pass

    combined = base_nums | reserved_nums

    for attempt in range(max_retries):
        if combined:
            next_num = max(combined) + 1
        else:
            next_num = 1
        candidate = f"T{next_num:04d}"

        if candidate not in (reserved_ids or set()) and _id_is_free(candidate):
            return candidate

        combined.add(next_num)
        print(
            f"[WARN] ID {candidate} は使用済み。リトライ {attempt + 1}/{max_retries}",
            file=sys.stderr,
        )
    raise RuntimeError(f"ID 採番が {max_retries} 回リトライしても成功しませんでした")


# ── slug 生成 ─────────────────────────────────────────────────────────────────

# 日本語テキストから英語スラグを生成するための単語マッピング（頻出語）
_JP_TO_EN: dict[str, str] = {
    "作成": "create", "実装": "implement", "開発": "develop", "設計": "design",
    "確認": "check", "検討": "review", "調査": "research", "分析": "analyze",
    "送付": "send", "返信": "reply", "連絡": "contact", "共有": "share",
    "更新": "update", "修正": "fix", "追加": "add", "削除": "remove",
    "整理": "organize", "準備": "prepare", "報告": "report", "提案": "propose",
    "資料": "doc", "カリキュラム": "curriculum", "研修": "training",
    "LP": "lp", "ランディングページ": "landing-page",
    "タスク": "task", "ミーティング": "meeting", "スケジュール": "schedule",
    "コンテンツ": "content", "エージェント": "agent", "講座": "course",
    "ゼミ": "seminar", "ハッカソン": "hackathon",
    "方針": "policy", "計画": "plan", "戦略": "strategy",
    "検証": "verify", "テスト": "test", "レビュー": "review",
    "仕様": "spec", "ドキュメント": "doc", "ラフ": "draft",
    "フォーマット": "format", "アナウンス": "announce",
    "AIコーチング": "ai-coaching", "AI": "ai", "BtoC": "btoc", "BtoB": "btob",
}


def _to_ascii_slug(text: str) -> str:
    """テキストから英小文字ハイフン区切りの slug を生成する（3-6 語）。

    日本語テキストも英語キーワードに変換して処理する。
    """
    # 事前マッピング変換
    result = text
    for jp, en in sorted(_JP_TO_EN.items(), key=lambda x: -len(x[0])):
        result = result.replace(jp, f" {en} ")

    # Unicode 正規化後、ASCII に変換
    try:
        normalized = unicodedata.normalize("NFKC", result)
    except Exception:
        normalized = result

    # ASCII 以外を除去、英数字のみ残す
    ascii_parts: list[str] = []
    current: list[str] = []
    for ch in normalized.lower():
        if ch.isascii() and (ch.isalnum() or ch in ("-", "_", " ")):
            current.append(ch if ch != "_" else "-")
        else:
            if current:
                ascii_parts.append("".join(current).strip("-"))
                current = []
    if current:
        ascii_parts.append("".join(current).strip("-"))

    # スペース/ハイフンで分割してトークン化
    tokens: list[str] = []
    for part in ascii_parts:
        for token in re.split(r"[\s\-]+", part):
            token = token.strip("-")
            if len(token) >= 2:
                tokens.append(token)

    # ストップワード除去（短い冠詞・前置詞等）
    stopwords = {"the", "a", "an", "in", "on", "at", "to", "of", "for", "and", "or"}
    tokens = [t for t in tokens if t not in stopwords]

    if not tokens:
        # フォールバック: hash で一意性確保
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"task-{h}"

    # 3-6 語に制限
    tokens = tokens[:6]
    if len(tokens) < 3 and len(tokens) > 0:
        # 語数が少なすぎる場合はそのまま使う
        pass

    return "-".join(tokens)


# ── 人物存在確認 ──────────────────────────────────────────────────────────────

def _person_exists_in_vault(name: str) -> bool:
    """vault/02_people/<name>.md が存在するか確認。"""
    candidate = PEOPLE_DIR / f"{name}.md"
    return candidate.exists()


# ── assignee 解決 ─────────────────────────────────────────────────────────────

_ENDO_ALIASES = {"遠藤雅俊", "Endo", "遠藤", "masatoshi.endo"}
_ENGINEERING_TYPES = {"engineering"}


def _resolve_assignee(assignee_raw: Optional[str], task_type: str) -> str:
    """D4 ロジックに従って assignee wikilink を解決する。

    Args:
        assignee_raw: action item から抽出した担当者名（None 可）
        task_type:    推論された type

    Returns:
        wikilink 文字列（例: "[[遠藤雅俊]]", "[[role:tech-lead]]"）
    """
    is_engineering = task_type in _ENGINEERING_TYPES

    if assignee_raw is None:
        # 担当が読み取れない
        return "[[role:tech-lead]]" if is_engineering else "[[遠藤雅俊]]"

    # Endo エイリアス
    if assignee_raw in _ENDO_ALIASES:
        return "[[遠藤雅俊]]"

    # vault/02_people/ に存在確認
    if _person_exists_in_vault(assignee_raw):
        return f"[[{assignee_raw}]]"

    # 存在しない人物
    return "[[role:tech-lead]]" if is_engineering else "[[遠藤雅俊]]"


# ── type 推論 ─────────────────────────────────────────────────────────────────

def _infer_type(content: str) -> str:
    """action item の内容から type を推論する。"""
    for type_name, keywords in _TYPE_KEYWORDS:
        for kw in keywords:
            if kw.lower() in content.lower():
                return type_name
    return "admin"


# ── priority 推論 ─────────────────────────────────────────────────────────────

def _infer_priority(content: str, due: Optional[str]) -> str:
    """action item の内容と期限から priority を推論する。"""
    for kw in _PRIORITY_P0_KEYWORDS:
        if kw in content:
            return "P0"
    for kw in _PRIORITY_P1_KEYWORDS:
        if kw in content:
            return "P1"

    # 期限が近い場合（3日以内なら P1）
    if due:
        try:
            due_date = datetime.strptime(due, "%Y-%m-%d").date()
            today = datetime.now(JST).date()
            delta = (due_date - today).days
            if delta <= 3:
                return "P1"
        except ValueError:
            pass

    return "P2"


# ── YAML scalar 安全エスケープ ────────────────────────────────────────────────

def _yaml_quote_str(s: str) -> str:
    """文字列を YAML double-quoted scalar として返す。

    frontmatter の title など、任意テキストを安全に埋め込むために使う。
    ダブルクオート内で必要なエスケープのみ適用:
        "  →  \\"
        \\  →  \\\\
        改行 →  \\n
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


# ── タスクファイル生成 ────────────────────────────────────────────────────────

def _build_task_content(
    task_id: str,
    slug: str,
    title: str,
    task_type: str,
    priority: str,
    assignee: str,
    project: Optional[str],
    related_meeting_stem: str,
    created: str,
    due: Optional[str],
    raw_line: str,
    purpose: Optional[str] = None,
    premise: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
) -> str:
    """タスク Markdown ファイルの内容を生成する。

    purpose / premise / acceptance_criteria が提供された場合は各 top-level セクションに差し込む。
    None の場合は規定のプレースホルダを埋める。
    フォーマット詳細は同スキルの SKILL.md を参照。
    """
    due_val = due if due else ""
    project_val = f'"[[{project}]]"' if project else '""'
    assignee_quoted = f'"{assignee}"'
    title_quoted = _yaml_quote_str(title)

    # 各セクションの本文を決定 (None → プレースホルダ)
    gaiyou_text = "// /plan-task で記入されます"  # 議事録由来は概要を自動生成しない

    if purpose is None:
        purpose_text = "// 議事録から推論不可。朝 review で記入してください"
    else:
        purpose_text = purpose

    if premise is None:
        premise_text = "- // 議事録から推論不可"
    else:
        premise_text = premise  # 既に Markdown bullet を含む想定

    if acceptance_criteria is None:
        dod_text = "- [ ] // /plan-task で記入されます"
    else:
        dod_text = acceptance_criteria  # Markdown bullet を含む想定

    project_relation_line = f"- プロジェクト: [[{project}]]" if project else ""

    content = f"""---
id: {task_id}
title: {title_quoted}
status: draft
type: {task_type}
priority: {priority}
assignee: {assignee_quoted}
project: {project_val}
spec_path: ""
related_meeting: "[[{related_meeting_stem}]]"
created: {created}
due: {due_val}
blocked_reason: ""
generated_by: meeting-summarizer
---

# {title}

## 元の依頼内容（議事録から抽出）

{raw_line}

関連議事録: [[{related_meeting_stem}]]

## 概要

{gaiyou_text}

## 目的（なぜやるか）

{purpose_text}

## 前提（いま捉えている状況）

{premise_text}

## ネクストアクション

- [ ] /plan-task で仕様化（engineering タスクの場合）
- [ ] 実装着手（/implement-task or 手動）

## 受け入れ基準（DoD）

{dod_text}

## 関連

- 議事録: [[{related_meeting_stem}]]
{project_relation_line}
"""
    return content


# ── 議事録の行番号操作 ────────────────────────────────────────────────────────

def _append_task_link_to_line(
    content: str, line_no: int, task_link: str
) -> str:
    """content の line_no 行（1-origin）末尾に task_link を追加する。

    行末に既にリンクがある場合はスキップ。
    """
    lines = content.split("\n")
    idx = line_no - 1  # 0-origin
    if idx < 0 or idx >= len(lines):
        return content

    line = lines[idx]
    # 既にリンク済みチェック
    if _ALREADY_LINKED_RE.search(line):
        return content

    lines[idx] = f"{line} → {task_link}"
    return "\n".join(lines)


def _append_derived_tasks_section(
    content: str,
    derived_tasks: list[dict],
) -> str:
    """議事録末尾に ## 派生タスク セクションを追加（または既存に追記）する。

    derived_tasks: [{"id": "T0118", "slug": "...", "title": "...", "assignee": "[[...]]"}, ...]
    """
    if not derived_tasks:
        return content

    # 既に ## 派生タスク セクションがあるか確認
    section_re = re.compile(r"^##\s+派生タスク\s*$", re.MULTILINE)
    m = section_re.search(content)

    # 追記するエントリ
    new_entries: list[str] = []
    for task in derived_tasks:
        task_stem = f"{task['id']}-{task['slug']}"
        assignee_display = re.sub(r"^\[\[|\]\]$", "", task.get("assignee", ""))
        entry = f"- [[{task_stem}]] - {task['title']} (assignee: {assignee_display})"
        new_entries.append(entry)

    new_block = "\n".join(new_entries)

    if m:
        # 既存セクションの末尾に追記（重複は避ける）
        section_start = m.end()
        # 既存セクション内容をチェック
        rest = content[section_start:]
        next_section = re.search(r"^##\s+", rest, re.MULTILINE)
        if next_section:
            existing_section = rest[: next_section.start()]
        else:
            existing_section = rest

        # 重複している ID は追記しない
        filtered_entries: list[str] = []
        for task in derived_tasks:
            task_stem = f"{task['id']}-{task['slug']}"
            if f"[[{task_stem}]]" not in existing_section:
                assignee_display = re.sub(r"^\[\[|\]\]$", "", task.get("assignee", ""))
                entry = f"- [[{task_stem}]] - {task['title']} (assignee: {assignee_display})"
                filtered_entries.append(entry)

        if not filtered_entries:
            return content

        insert_pos = section_start
        # 既存セクション末尾を探す
        if next_section:
            insert_pos = section_start + next_section.start()
        else:
            insert_pos = len(content)

        # 末尾の改行を調整
        prefix = content[:insert_pos].rstrip("\n") + "\n"
        suffix = content[insert_pos:].lstrip("\n")
        addition = "\n".join(filtered_entries) + "\n"
        if suffix:
            return prefix + addition + "\n" + suffix
        return prefix + addition
    else:
        # 新規セクションを末尾に追加
        tail = content.rstrip("\n")
        section = "\n\n## 派生タスク\n\n" + new_block + "\n"
        return tail + section


# ── メイン処理 ────────────────────────────────────────────────────────────────

def process(
    meeting_path: Path,
    action_items: list[dict],
    dry_run: bool,
    owner_inferences: Optional[dict[str, dict]] = None,
) -> dict:
    """action items からタスクを生成し、議事録を更新する。

    Args:
        meeting_path:     議事録ファイルのパス
        action_items:     extract_action_items.py の出力リスト
        dry_run:          True の場合は実ファイルを作成しない
        owner_inferences: _load_owner_inferences() の戻り値（item_content キーの dict）。
                          None または空 dict の場合は現行挙動（全件起票）。

    Returns:
        result dict (meeting, skipped_reason, created, failed, skipped, content_mismatch_count, mismatches)
    """
    meeting_name = meeting_path.name

    # 議事録読み込み
    try:
        meeting_content = meeting_path.read_text(encoding="utf-8")
    except OSError as e:
        return {
            "meeting": meeting_name,
            "skipped_reason": f"meeting_read_error: {e}",
            "created": [],
            "failed": [],
            "skipped": [],
            "content_mismatch_count": 0,
            "mismatches": [],
        }

    # tasks_extracted_at チェック（冪等性）
    if _fm_field_exists(meeting_content, "tasks_extracted_at"):
        val = _read_fm_field(meeting_content, "tasks_extracted_at")
        if val:
            return {
                "meeting": meeting_name,
                "skipped_reason": "already_extracted",
                "created": [],
                "failed": [],
                "skipped": [],
                "content_mismatch_count": 0,
                "mismatches": [],
            }

    # frontmatter から議事録メタ読み取り
    meeting_project_raw = _read_fm_field(meeting_content, "project")

    # project: wikilink から slug を取得（例: "[[godai-ai-training]]" → "godai-ai-training"）
    meeting_project: Optional[str] = None
    if meeting_project_raw and meeting_project_raw not in ("", "unclassified", '""', "''"):
        m = re.search(r"\[\[([^\]]+)\]\]", meeting_project_raw)
        if m:
            meeting_project = m.group(1)

    # 関連議事録のリンク用 stem（拡張子なし）
    related_meeting_stem = meeting_path.stem

    today_jst = datetime.now(JST).strftime("%Y-%m-%d")
    now_jst_iso = datetime.now(JST).isoformat(timespec="seconds")

    created_tasks: list[dict] = []
    failed_tasks: list[dict] = []
    skipped_tasks: list[dict] = []         # owner=other でスキップした item
    mismatches: list[dict] = []            # owner_inferences content 不一致リスト
    content_mismatch_count: int = 0

    # owner_inferences が空 dict の場合は現行挙動
    use_owner_inferences = bool(owner_inferences)

    # 議事録の更新用コピー（行末追記を累積する）
    updated_meeting_content = meeting_content

    # 連続採番のための仮予約セット（dry-run / 同セッション内の重複防止）
    reserved_ids: set[str] = set()

    for item in action_items:
        line_no: int = item.get("line_no", 0)
        content_text: str = item.get("content", "")
        assignee_raw: Optional[str] = item.get("assignee_raw")
        due: Optional[str] = item.get("due")
        raw_line: str = item.get("raw_line", "")

        # ── owner 推論結果の適用 ──────────────────────────────────────────────
        item_purpose: Optional[str] = None
        item_premise: Optional[str] = None
        item_acceptance_criteria: Optional[str] = None

        if use_owner_inferences:
            lookup_key = content_text.strip()
            inference = owner_inferences.get(lookup_key)  # type: ignore[union-attr]

            if inference is None:
                # content 不一致: 現行挙動（全件起票）でフォールバック
                content_mismatch_count += 1
                mismatches.append({"line_no": line_no, "content": content_text})
                print(
                    f'[WARN] owner_inferences の item_content がマッチしません: "{content_text!r}"',
                    file=sys.stderr,
                )
            else:
                owner_val = inference.get("owner", "unclear")

                if owner_val == "other":
                    # スキップ: タスクファイルも議事録逆リンクも作成しない
                    skipped_tasks.append(
                        {
                            "content": content_text,
                            "owner": "other",
                            "reason": "agent_inferred_other",
                        }
                    )
                    if dry_run:
                        print(
                            f"[DRY-RUN] owner=other のためスキップ: {content_text!r}",
                            file=sys.stderr,
                        )
                    continue  # 次の action item へ

                # owner == "endo" or "unclear": 起票。purpose / premise / acceptance_criteria を渡す
                raw_purpose = inference.get("purpose")
                raw_premise = inference.get("premise")
                raw_acceptance = inference.get("acceptance_criteria")
                item_purpose = raw_purpose if isinstance(raw_purpose, str) and raw_purpose.strip() else None
                item_premise = raw_premise if isinstance(raw_premise, str) and raw_premise.strip() else None
                item_acceptance_criteria = raw_acceptance if isinstance(raw_acceptance, str) and raw_acceptance.strip() else None

        # type / priority / slug 推論
        task_type = _infer_type(content_text)
        priority = _infer_priority(content_text, due)
        slug = _to_ascii_slug(content_text)

        # assignee 解決
        assignee = _resolve_assignee(assignee_raw, task_type)

        # ID 採番
        try:
            task_id = _allocate_id(reserved_ids=reserved_ids)
        except RuntimeError as e:
            failed_tasks.append(
                {"content": content_text, "error": f"ID 採番失敗: {e}"}
            )
            print(f"[ERROR] ID 採番失敗: {e}", file=sys.stderr)
            continue

        # 採番した ID を仮予約（同セッション内の重複防止）
        reserved_ids.add(task_id)

        task_stem = f"{task_id}-{slug}"
        task_path = TASKS_DIR / f"{task_stem}.md"
        task_link = f"[[{task_stem}]]"

        # タスクファイル内容生成
        try:
            task_content = _build_task_content(
                task_id=task_id,
                slug=slug,
                title=content_text,
                task_type=task_type,
                priority=priority,
                assignee=assignee,
                project=meeting_project,
                related_meeting_stem=related_meeting_stem,
                created=today_jst,
                due=due,
                raw_line=raw_line,
                purpose=item_purpose,
                premise=item_premise,
                acceptance_criteria=item_acceptance_criteria,
            )
        except Exception as e:
            failed_tasks.append(
                {"content": content_text, "error": f"タスク内容生成失敗: {e}"}
            )
            print(f"[ERROR] タスク内容生成失敗: {e}", file=sys.stderr)
            continue

        if not dry_run:
            # Write 直前の再確認
            if not _id_is_free(task_id):
                failed_tasks.append(
                    {"content": content_text, "error": f"ID {task_id} が Write 直前に使用中"}
                )
                print(
                    f"[ERROR] ID {task_id} が Write 直前に使用中。スキップします。",
                    file=sys.stderr,
                )
                continue

            try:
                task_path.write_text(task_content, encoding="utf-8")
            except OSError as e:
                failed_tasks.append(
                    {"content": content_text, "error": f"ファイル書き込み失敗: {e}"}
                )
                print(f"[ERROR] タスクファイル書き込み失敗: {e}", file=sys.stderr)
                continue

        # 議事録の対象行末にリンク追記
        if line_no > 0:
            updated_meeting_content = _append_task_link_to_line(
                updated_meeting_content, line_no, task_link
            )

        created_tasks.append(
            {
                "id": task_id,
                "slug": slug,
                "assignee": assignee,
                "type": task_type,
                "priority": priority,
                "due": due,
                "title": content_text,
            }
        )

        if dry_run:
            print(
                f"[DRY-RUN] タスク作成: {task_stem} (assignee={assignee}, type={task_type})",
                file=sys.stderr,
            )

    # 全件成功または 0 件の場合のみ議事録を更新
    all_succeeded = len(failed_tasks) == 0

    if not dry_run and all_succeeded:
        # 派生タスク セクション追記
        if created_tasks:
            updated_meeting_content = _append_derived_tasks_section(
                updated_meeting_content, created_tasks
            )

        # tasks_extracted_at フラグ書き込み
        try:
            updated_meeting_content = _update_fm_field(
                updated_meeting_content, "tasks_extracted_at", now_jst_iso
            )
        except ValueError as e:
            print(f"[WARN] tasks_extracted_at 書き込み失敗: {e}", file=sys.stderr)

        # 議事録ファイル書き戻し
        try:
            meeting_path.write_text(updated_meeting_content, encoding="utf-8")
        except OSError as e:
            print(f"[ERROR] 議事録ファイル書き戻し失敗: {e}", file=sys.stderr)

    elif dry_run:
        # dry-run の場合は tasks_extracted_at を追記した想定内容を表示
        if created_tasks:
            preview = _append_derived_tasks_section(updated_meeting_content, created_tasks)
            try:
                preview = _update_fm_field(preview, "tasks_extracted_at", now_jst_iso)
            except ValueError:
                pass
            print(
                "[DRY-RUN] 議事録更新プレビュー（実際には書き込みません）:",
                file=sys.stderr,
            )
            # 差分の先頭 30 行だけ表示
            preview_lines = preview.split("\n")[:30]
            for ln in preview_lines:
                print(f"  {ln}", file=sys.stderr)
    elif not all_succeeded:
        print(
            "[WARN] 部分失敗のため tasks_extracted_at を立てません（次回再試行）",
            file=sys.stderr,
        )

    return {
        "meeting": meeting_name,
        "skipped_reason": None,
        "created": created_tasks,
        "failed": failed_tasks,
        "skipped": skipped_tasks,
        "content_mismatch_count": content_mismatch_count,
        "mismatches": mismatches,
    }


# ── メインエントリポイント ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="action items から vault/05_tasks/ にタスクファイルを生成する"
    )
    parser.add_argument(
        "--meeting",
        required=True,
        metavar="<meeting-md-path>",
        help="議事録 Markdown ファイルのパス",
    )
    parser.add_argument(
        "--action-items",
        required=True,
        metavar="<json-path or ->",
        help="extract_action_items.py の出力 JSON パス（- で stdin）",
    )
    parser.add_argument(
        "--owner-inferences",
        metavar="<json-path or ->",
        default=None,
        help=(
            "owner 推論結果 JSON のパス（- で stdin）。"
            "未指定時は owner 判定なし（T0116 互換挙動）。"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実ファイル作成・議事録書き換えを行わず、計画のみ出力",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="JSON を整形して出力",
    )
    args = parser.parse_args()

    # 議事録パス検証
    meeting_path = Path(args.meeting).expanduser().resolve()
    if not meeting_path.exists():
        print(f"[ERROR] 議事録ファイルが見つかりません: {meeting_path}", file=sys.stderr)
        sys.exit(1)
    if not _is_within_vault(meeting_path):
        print(
            f"[ERROR] VAULT_DIR 外のファイルは処理できません: {meeting_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # action items JSON 読み込み
    if args.action_items == "-":
        try:
            raw_json = sys.stdin.read()
        except KeyboardInterrupt:
            sys.exit(1)
    else:
        items_path = Path(args.action_items).expanduser().resolve()
        if not _is_within_vault(items_path):
            print(
                f"[ERROR] vault 外の JSON パスは許可されていません: {items_path}",
                file=sys.stderr,
            )
            sys.exit(2)
        if not items_path.exists():
            print(f"[ERROR] action items JSON が見つかりません: {items_path}", file=sys.stderr)
            sys.exit(1)
        try:
            raw_json = items_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[ERROR] JSON 読み込み失敗: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        action_items: list[dict] = json.loads(raw_json)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON パース失敗: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(action_items, list):
        print("[ERROR] action items は JSON 配列である必要があります", file=sys.stderr)
        sys.exit(1)

    # owner inferences 読み込み（任意）
    owner_inferences_map: dict[str, dict] = {}
    if args.owner_inferences is not None:
        if args.owner_inferences != "-":
            inferences_path = Path(args.owner_inferences).expanduser().resolve()
            if not _is_within_vault(inferences_path):
                print(
                    f"[ERROR] vault 外の JSON パスは許可されていません: {inferences_path}",
                    file=sys.stderr,
                )
                sys.exit(2)
        owner_inferences_map = _load_owner_inferences(args.owner_inferences)

    result = process(
        meeting_path,
        action_items,
        dry_run=args.dry_run,
        owner_inferences=owner_inferences_map if owner_inferences_map else None,
    )

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
