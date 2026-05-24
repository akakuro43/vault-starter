#!/usr/bin/env python3
"""
extract_action_items.py: 議事録の ## ネクストアクション セクションから
action items を構造化 JSON で抽出する。

Usage:
  python3 extract_action_items.py <meeting-md-path> [--pretty]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── パス定数 ──────────────────────────────────────────────────────────────────
# VAULT_PATH 環境変数で上書き可。デフォルトはリポジトリ直下の vault/
VAULT_DIR = Path(os.environ.get('VAULT_PATH', Path(__file__).resolve().parents[3] / 'vault')).expanduser().resolve()

# ── 正規表現 ──────────────────────────────────────────────────────────────────

# ## ネクストアクション セクション開始
_SECTION_START_RE = re.compile(r"^##\s+ネクストアクション\s*$", re.MULTILINE)

# 次の ## 見出し（### は許容、## のみ終了トリガー）
_NEXT_SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)

# action item 行: `- [ ] <content> — 担当: [[assignee]] / 期限: YYYY-MM-DD`
# ダッシュは em dash (—) を基本とするが半角 - も許容（R2 対策）
# 担当・期限は両方省略可
# 担当は複数人（[[A]], [[B]] 形式）も許容: 最初の [[...]] のみを assignee に採用
_ACTION_ITEM_RE = re.compile(
    r"^-\s+\[\s*\]\s+"                                           # - [ ]
    r"(?P<content>.+?)"                                           # 内容（非貪欲）
    r"(?:\s+[—\-]\s*担当[:：]\s*\[\[(?P<assignee>[^\]]+)\]\]"    # 担当（省略可）
    r"(?:,\s*\[\[[^\]]+\]\])*\s*)?"                              # 複数担当者の残り（無視）
    r"(?:/\s*期限[:：]\s*(?P<due>\d{4}-\d{2}-\d{2}))?"           # 期限（省略可）
    r"\s*$",
    re.MULTILINE,
)

# 既にタスクリンクが追記済みの行（冪等性チェック）
_ALREADY_LINKED_RE = re.compile(r"→\s*\[\[T\d{4}")

# placeholder 行パターン（スキップ対象）
_PLACEHOLDER_RE = re.compile(
    r"^-\s+\[\s*\]\s*[（(]?(明示的なアクションなし|なし|N/A|n/a)[）)]?\s*$"
)


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


# ── frontmatter スキップ ──────────────────────────────────────────────────────

def _skip_frontmatter(content: str) -> tuple[str, int]:
    """content 先頭の frontmatter (---...---) をスキップし、
    本文と frontmatter の行数を返す。

    Returns:
        (body_text, frontmatter_line_count)
    """
    if not content.startswith("---"):
        return content, 0

    lines = content.split("\n")
    if len(lines) < 2:
        return content, 0

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return content, 0

    body = "\n".join(lines[end_idx + 1:])
    return body, end_idx + 1  # +1 for the closing ---


# ── セクション抽出 ────────────────────────────────────────────────────────────

def extract_next_action_section(body: str) -> tuple[str, int] | tuple[None, None]:
    """body から ## ネクストアクション セクションのテキストと開始行番号を返す。

    Returns:
        (section_text, section_start_line_no_in_body) または (None, None)
    """
    m = _SECTION_START_RE.search(body)
    if m is None:
        return None, None

    section_start = m.end()

    # 次の ## 見出しの位置を探す
    next_m = _NEXT_SECTION_RE.search(body, section_start)
    if next_m:
        section_text = body[section_start:next_m.start()]
    else:
        section_text = body[section_start:]

    # セクション開始行番号（body 内の行番号）
    section_start_line = body[: m.start()].count("\n")

    return section_text, section_start_line


# ── action items 抽出 ─────────────────────────────────────────────────────────

def extract_action_items(meeting_path: Path) -> list[dict]:
    """議事録ファイルから action items のリストを返す。

    各要素:
        line_no         : ファイル内行番号 (1-origin)
        content         : action item の内容
        assignee_raw    : 担当者の raw 文字列（[[]] の中身）。なければ None
        assignee_resolved: 常に null（Step 2 で解決）
        due             : 期限 (YYYY-MM-DD)。なければ None
        raw_line        : 元の行テキスト
    """
    if not meeting_path.exists():
        print(f"[ERROR] ファイルが見つかりません: {meeting_path}", file=sys.stderr)
        sys.exit(1)

    if not _is_within_vault(meeting_path):
        print(f"[ERROR] VAULT_DIR 外のファイルは処理できません: {meeting_path}", file=sys.stderr)
        sys.exit(1)

    try:
        content = meeting_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[ERROR] ファイル読み込み失敗: {e}", file=sys.stderr)
        sys.exit(1)

    body, fm_line_count = _skip_frontmatter(content)
    section_text, section_start_line = extract_next_action_section(body)

    if section_text is None:
        print(
            f"[WARN] ## ネクストアクション セクションが見つかりません: {meeting_path.name}",
            file=sys.stderr,
        )
        return []

    items: list[dict] = []

    # raw ファイル全行を一度だけ splitlines して辞書を作る
    # これにより空行の有無に関わらず行番号を直接特定できる
    all_file_lines = content.splitlines()
    # 行テキスト → ファイル行番号 (1-origin) のマップ
    # 同一テキストが複数行あるケースに対応するため先頭一致リストを作る
    stripped_to_line_nos: dict[str, list[int]] = {}
    for idx, raw_line in enumerate(all_file_lines):
        key = raw_line.strip()
        if key not in stripped_to_line_nos:
            stripped_to_line_nos[key] = []
        stripped_to_line_nos[key].append(idx + 1)  # 1-origin

    # section 内を行単位で処理（section_text はセクション見出し行の次から）
    # 既存の section_start_line を使って section 内の各行のファイル行番号を算出する
    # section_start_line は body 内での ## ネクストアクション 行の 0-origin 番号
    # ファイル内の ## ネクストアクション 行番号 (1-origin) = fm_line_count + section_start_line + 1
    section_header_file_line = fm_line_count + section_start_line + 1

    # section_text は ## ネクストアクション 行の m.end() 以降
    # m.end() は行末（\n を含む場合は \n の次）を指すため、
    # splitlines で得た行リストで section_header_file_line の次行から数える
    section_lines = section_text.splitlines()

    # 重複行の逐次割り当て用カーソル（各行テキストの何番目を使ったか）
    used_cursor: dict[str, int] = {}

    for i, line in enumerate(section_lines):
        # ファイル内行番号: セクション見出し行の次行 + i
        file_line_no = section_header_file_line + 1 + i

        stripped = line.strip()

        # - [ ] で始まらない行はスキップ（サブ見出し ### 等も含む）
        if not stripped.startswith("- ["):
            continue

        # placeholder 行スキップ
        if _PLACEHOLDER_RE.match(stripped):
            continue

        # 既にタスクリンク済みの行はスキップ（冪等性）
        if _ALREADY_LINKED_RE.search(stripped):
            continue

        m = _ACTION_ITEM_RE.match(stripped)
        if m is None:
            print(
                f"[WARN] action item パースに失敗（行 {file_line_no}）: {stripped!r}",
                file=sys.stderr,
            )
            continue

        # 行番号をマップから精密に確定する（重複行対応）
        candidates = stripped_to_line_nos.get(stripped, [])
        cursor = used_cursor.get(stripped, 0)
        if cursor < len(candidates):
            file_line_no = candidates[cursor]
            used_cursor[stripped] = cursor + 1
        # candidates が空または cursor 超過の場合は計算値をそのまま使う

        content_val = m.group("content").strip()
        assignee_raw = m.group("assignee")
        due = m.group("due")

        # 担当が複数人（"[[A]], [[B]]" 形式）の場合は最初の1人を採用
        if assignee_raw and "]]" in assignee_raw:
            # 既に単一リンクの中身が取れているが念のため先頭を取る
            # 例: "遠藤雅俊]], [[Kazunari Chiba" → "遠藤雅俊"
            assignee_raw = assignee_raw.split("]]")[0]

        items.append(
            {
                "line_no": file_line_no,
                "content": content_val,
                "assignee_raw": assignee_raw if assignee_raw else None,
                "assignee_resolved": None,
                "due": due if due else None,
                "raw_line": stripped,
            }
        )

    return items


# ── メインエントリポイント ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="議事録の ## ネクストアクション セクションから action items を抽出する"
    )
    parser.add_argument(
        "meeting_path",
        metavar="<meeting-md-path>",
        help="議事録 Markdown ファイルのパス",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="JSON を整形して出力",
    )
    args = parser.parse_args()

    meeting_path = Path(args.meeting_path).expanduser().resolve()
    items = extract_action_items(meeting_path)

    indent = 2 if args.pretty else None
    print(json.dumps(items, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
