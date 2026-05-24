#!/usr/bin/env python3
"""
update_last_activity.py: 01_projects/<slug>/<slug>.md の last_activity フィールドを更新する。

仕様:
  - 新しい日付が現在の last_activity より新しい場合のみ更新（巻き戻さない）
  - 等しい or 古い場合は no-op で done を返す
  - frontmatter のキー順は維持する

入出力:
  --project SLUG --date YYYY-MM-DD
  → 標準出力に "updated: <slug> <old> -> <new>" or "noop: <slug> already <date>"
  終了コード: 0=成功, 1=エラー
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    PROJECTS_DIR,
    parse_frontmatter,
    update_frontmatter_field,
)

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def update(slug: str, new_date: str) -> str:
    if not _DATE_RE.match(new_date):
        raise ValueError(f'date must be YYYY-MM-DD: {new_date}')

    home = PROJECTS_DIR / slug / f'{slug}.md'
    if not home.exists():
        raise FileNotFoundError(f'project home not found: {home}')

    content = home.read_text(encoding='utf-8')
    fm, _ = parse_frontmatter(content)
    if fm.get('type') != 'project':
        raise ValueError(f'not a project file: {home}')

    old = str(fm.get('last_activity') or '')
    if old and old >= new_date:
        return f'noop: {slug} already {old}'

    new_content = update_frontmatter_field(content, 'last_activity', new_date)
    home.write_text(new_content, encoding='utf-8')
    return f'updated: {slug} {old or "(none)"} -> {new_date}'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Project slug (例: godai-ai-training)')
    parser.add_argument('--date',    required=True, help='新しい last_activity (YYYY-MM-DD)')
    args = parser.parse_args()

    try:
        msg = update(args.project, args.date)
    except (FileNotFoundError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)
    print(msg)


if __name__ == '__main__':
    main()
