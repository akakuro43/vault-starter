#!/usr/bin/env python3
"""
scan_inbox.py: 00_inbox/meeting_transcripts/ 直下の未処理トランスクリプトを列挙する。

processed/ 配下は除外。frontmatter の `type: transcript` のみ対象。

出力:
  JSON 配列（標準出力）
  例:
    [
      {
        "path": "/Users/.../00_inbox/meeting_transcripts/2026-05-01_定例会.md",
        "date": "2026-05-01",
        "title": "定例会",
        "owner": "masatoshi.endo@degisense.com",
        "drive_id": "1abc...",
        "drive_filename": "TRANSCRIPT_26.05.01_定例会_..."
      },
      ...
    ]

オプション:
  --pretty        : 整形して出力
  --limit N       : 先頭N件のみ
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# lib をインポートできるように親ディレクトリを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import INBOX_TRANSCRIPTS_DIR, parse_frontmatter


def scan() -> list[dict]:
    if not INBOX_TRANSCRIPTS_DIR.exists():
        return []

    results = []
    for path in sorted(INBOX_TRANSCRIPTS_DIR.glob('*.md')):
        # processed/ サブフォルダ配下は glob('*.md') では拾わない（直下のみ）
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            continue

        fm, _ = parse_frontmatter(content)
        if fm.get('type') != 'transcript':
            continue

        results.append({
            'path': str(path),
            'date': str(fm.get('date', '')),
            'title': str(fm.get('title', '')),
            'owner': str(fm.get('owner', '')),
            'drive_id': str(fm.get('drive_id', '')),
            'drive_filename': str(fm.get('drive_filename', '')),
        })

    # 古い順に処理したいので date 昇順
    results.sort(key=lambda r: (r['date'], r['title']))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pretty', action='store_true', help='整形出力')
    parser.add_argument('--limit', type=int, help='先頭N件のみ')
    args = parser.parse_args()

    results = scan()
    if args.limit:
        results = results[:args.limit]

    indent = 2 if args.pretty else None
    print(json.dumps(results, ensure_ascii=False, indent=indent))


if __name__ == '__main__':
    main()
