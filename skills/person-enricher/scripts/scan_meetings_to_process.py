#!/usr/bin/env python3
"""
scan_meetings_to_process.py: 未処理の議事録を抽出する。

state.json の `last_processed_meeting_date` を読んで、それ以降の日付の議事録のうち、
新形式（frontmatter の `participants:` フィールドあり）のものだけ列挙する。

旧形式（fetch_mtgs.py 由来・participants が plain text）はスキップする。

出力:
  JSON 配列。各要素は { path, date, title, participants, transcript, project, client }
  participants は wikilink 中身（例: ["千葉宏輝", "渡邉隆"]）。

オプション:
  --pretty
  --since YYYY-MM-DD     state.json を無視して特定日以降を取得
  --include-old-format   旧形式（participants 無し）も含める（デバッグ用）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    MEETINGS_DIR,
    STATE_FILE,
    extract_participants_from_meeting,
    get_meeting_metadata,
    parse_frontmatter,
)


def load_last_processed() -> str:
    """state.json から last_processed_meeting_date を取得。なければ空文字。"""
    if not STATE_FILE.exists():
        return ''
    try:
        state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return str(state.get('last_processed_meeting_date') or '')
    except json.JSONDecodeError:
        return ''


def scan(since: str = '', include_old: bool = False) -> list[dict]:
    if not since:
        since = load_last_processed()

    results = []
    for path in sorted(MEETINGS_DIR.glob('*.md')):
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            continue

        fm, _ = parse_frontmatter(content)
        if fm.get('type') != 'meeting':
            continue

        date = str(fm.get('date', ''))
        if since and date <= since:
            continue

        # 新形式（participants frontmatter あり）かどうか判定
        participants = extract_participants_from_meeting(content)
        is_new_format = bool(participants)

        if not is_new_format and not include_old:
            continue

        meta = {
            'path': str(path),
            'date': date,
            'title': str(fm.get('title', '')),
            'participants': participants,
            'transcript': str(fm.get('transcript', '')),
            'project': fm.get('project'),
            'client': fm.get('client'),
            'is_new_format': is_new_format,
        }
        results.append(meta)

    # 古い順
    results.sort(key=lambda r: (r['date'], r['title']))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pretty', action='store_true')
    parser.add_argument('--since', type=str, default='')
    parser.add_argument('--include-old-format', action='store_true')
    args = parser.parse_args()

    results = scan(since=args.since, include_old=args.include_old_format)
    indent = 2 if args.pretty else None
    print(json.dumps(results, ensure_ascii=False, indent=indent))


if __name__ == '__main__':
    main()
