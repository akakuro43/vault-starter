#!/usr/bin/env python3
"""
cleanup_person_notes.py: 02_people/<人物>.md を build_people.py 退役に向けて整理する。

build_people.py 由来の以下要素を除去:
  - `## 担当アクション（直近MTGより）` セクション
  - `*このファイルは build_people.py により自動生成されました（YYYY-MM-DD）*` フッター
  - 上記フッターと対の `*AIが学んだ情報は随時このファイルに追記してください*` 行

mode:
  phase1        担当アクション + フッターのみ除去（観察ログ・プロファイル・参加履歴は保持）
  phase2-reset  上記に加えて、再分析向けに以下も初期化:
                  - `## 観察ログ` セクション削除
                  - `## プロファイル` セクション削除
                  - `## 参加したミーティング` セクション削除
                  - frontmatter `meeting_count: 0`
                  - frontmatter `last_meeting: ""`
                  - frontmatter `related_projects: []`
                  - 基本情報 table の MTG参加数/最終MTG セルを `0件` / `-`

オプション:
  --dry-run      変更内容を stdout に diff 表示するだけ。ファイル書き換えなし
  --person <名前>  特定 1 人のみ対象（dry-run 確認用）
  --mode <mode>  phase1 | phase2-reset （必須）
  --pretty       diff を整形して見やすく

副作用:
  指定モードに応じて 02_people/*.md を書き換える。frontmatter type: person 以外は skip。
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    PEOPLE_DIR,
    find_section_bounds,
    parse_frontmatter,
    update_frontmatter_field,
)


# ── 除去対象パターン ────────────────────────────────────────
_BUILD_PEOPLE_FOOTER_RE = re.compile(
    r'\n*---\n+\*このファイルは build_people\.py により自動生成されました[^*\n]*\*\s*\n'
    r'\*AIが学んだ情報は随時このファイルに追記してください\*\s*\n?',
    re.MULTILINE,
)

# 単独パターン（フッターが部分的に残った場合の fallback）
_BUILD_PEOPLE_MARKER_RE = re.compile(
    r'^\*このファイルは build_people\.py により自動生成されました[^*\n]*\*\s*\n?',
    re.MULTILINE,
)
_AI_LEARNED_NOTE_RE = re.compile(
    r'^\*AIが学んだ情報は随時このファイルに追記してください\*\s*\n?',
    re.MULTILINE,
)


def _remove_section(body: str, header: str) -> str:
    """`## <header>` セクションを完全に除去し、前後の改行を整える。"""
    bounds = find_section_bounds(body, header)
    if not bounds:
        return body
    start, end = bounds
    # 直前の余分な空行も削除（過剰な空白を避ける）
    while start > 0 and body[start - 1] == '\n':
        start -= 1
    return body[:start] + ('\n' if body[end:].lstrip('\n') else '') + body[end:].lstrip('\n')


def _reset_basic_info_table(body: str) -> str:
    """基本情報 table の MTG参加数 / 最終MTG / 関連PJ セルを baseline 化。"""
    body = re.sub(
        r'(\|\s*MTG参加数\s*\|\s*)(\d+件|不明|-)(\s*\|)',
        r'\g<1>0件\g<3>',
        body,
    )
    body = re.sub(
        r'(\|\s*最終MTG\s*\|\s*)([\d-]+|不明|-|\(なし\))(\s*\|)',
        r'\g<1>-\g<3>',
        body,
    )
    # 関連PJ セルは複雑な内容（wikilink リスト等）を持ちうるので 1 行内のみ書き換え
    body = re.sub(
        r'(\|\s*関連PJ\s*\|\s*)([^|\n]*?)(\s*\|)',
        r'\g<1>-\g<3>',
        body,
    )
    return body


def _strip_footer(content: str) -> str:
    """build_people.py 由来のフッター行とその上の `---` を除去。"""
    new = _BUILD_PEOPLE_FOOTER_RE.sub('\n', content)
    new = _BUILD_PEOPLE_MARKER_RE.sub('', new)
    new = _AI_LEARNED_NOTE_RE.sub('', new)
    # 末尾の余分な空行を圧縮
    new = re.sub(r'\n{3,}\Z', '\n', new)
    if not new.endswith('\n'):
        new += '\n'
    return new


def _apply_phase1(content: str) -> str:
    """phase1: 担当アクション section + フッターのみ除去。"""
    fm_match = re.match(r'^(---\n.*?\n---\n?)', content, re.DOTALL)
    if not fm_match:
        return content
    fm_block = fm_match.group(1)
    body = content[fm_match.end():]

    body = _remove_section(body, '担当アクション（直近MTGより）')
    # `担当アクション` 表記揺れにも対応
    body = _remove_section(body, '担当アクション')

    new_content = fm_block + body
    new_content = _strip_footer(new_content)
    return new_content


def _apply_phase2_reset(content: str) -> str:
    """phase2-reset: phase1 の処理に加えて、観察/プロファイル/参加履歴を初期化。"""
    new = _apply_phase1(content)

    # frontmatter のリセット
    new = update_frontmatter_field(new, 'meeting_count', '0')
    new = update_frontmatter_field(new, 'last_meeting', '""')

    # related_projects は list なので update_frontmatter_field では書けない → 専用処理
    new = re.sub(
        r'^related_projects\s*:[^\n]*(?:\n(?:[ \t]+[^\n]*|-[^\n]*))*',
        'related_projects: []',
        new,
        count=1,
        flags=re.MULTILINE,
    )

    # body の sections を削除
    fm_match = re.match(r'^(---\n.*?\n---\n?)', new, re.DOTALL)
    if not fm_match:
        return new
    fm_block = fm_match.group(1)
    body = new[fm_match.end():]

    body = _remove_section(body, '観察ログ')
    body = _remove_section(body, 'プロファイル')
    body = _remove_section(body, '参加したミーティング')

    # 基本情報 table のセルを baseline 化
    body = _reset_basic_info_table(body)

    return fm_block + body


def _process_file(path: Path, mode: str) -> tuple[str, str]:
    """ファイルを読み、変換後の文字列を返す。(before, after)。"""
    before = path.read_text(encoding='utf-8')
    fm, _ = parse_frontmatter(before)
    if fm.get('type') != 'person':
        return before, before

    if mode == 'phase1':
        after = _apply_phase1(before)
    elif mode == 'phase2-reset':
        after = _apply_phase2_reset(before)
    else:
        raise ValueError(f'unknown mode: {mode}')
    return before, after


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=['phase1', 'phase2-reset'])
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--person', default=None, help='特定 1 人だけ対象')
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args()

    if not PEOPLE_DIR.exists():
        print(f'error: {PEOPLE_DIR} not found', file=sys.stderr)
        sys.exit(1)

    if args.person:
        targets = [PEOPLE_DIR / f'{args.person}.md']
        if not targets[0].exists():
            print(f'error: person not found: {targets[0]}', file=sys.stderr)
            sys.exit(1)
    else:
        targets = sorted(PEOPLE_DIR.glob('*.md'))

    changed = 0
    skipped = 0
    unchanged = 0

    for path in targets:
        before, after = _process_file(path, args.mode)
        if before == after:
            unchanged += 1
            continue
        # 非 person ファイル（fm type 違い）は _process_file 内で before==after
        if args.dry_run:
            if args.pretty:
                diff = difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f'{path.name} (before)',
                    tofile=f'{path.name} (after)',
                    n=2,
                )
                sys.stdout.write(''.join(diff))
                sys.stdout.write('\n')
            else:
                print(f'WOULD-CHANGE: {path.name}')
        else:
            path.write_text(after, encoding='utf-8')
            print(f'changed: {path.name}')
        changed += 1

    summary = f'\nmode={args.mode}  changed={changed} unchanged={unchanged}  total={len(targets)}'
    if args.dry_run:
        summary += '  [DRY-RUN: no files written]'
    print(summary)


if __name__ == '__main__':
    main()
