#!/usr/bin/env python3
"""
scan_unresolved.py: vault 全体から未解決 wikilink を抽出する。

「未解決」= vault 内にファイル名一致するノートが存在しない wikilink。
person / project スコープ外（company など）は除外。

スキャン対象から除外されるパス:
  - 00_inbox/        生データ
  - ops/             運用基盤
  - 99_system/templates/  プレースホルダ wikilink を含む

出力:
  JSON 配列。各要素は { link, kind, appearances }
    - link: wikilink テキスト
    - kind: "person" | "project" | "concept" | "unknown"  (company は出力に含めない)
    - appearances: [{file, line, context}, ...]

オプション:
  --pretty      整形出力
  --include-company   company kind も含める（デバッグ用）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    FIELD_TO_KIND,
    VAULT_DIR,
    _CONCEPT_SUFFIX_RE,
    enumerate_all_locations,
    extract_wikilinks,
    get_existing_company_names,
    is_scan_excluded,
    load_excluded_links,
)

# ASCII slug パターン（project らしさ）
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9_-]*$')
# 日本語含む（人物らしさ）
_JP_RE = re.compile(r'[぀-ヿ一-鿿]')
# 日付プレフィックス（議事録・トランスクリプトのファイル名規約）
_DATE_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2}')
# 会議らしさを示す末尾語
_MEETING_SUFFIX_RE = re.compile(r'(ミーティング|MTG|会議|議事録)$')


def determine_kind(link: str, appearances: list[dict]) -> str:
    """文字列パターン（強い証拠）→ field コンテキスト（多数決）→ 弱パターン の順で判定。

    返り値:
      - "person"  : 人物候補
      - "project" : プロジェクト候補
      - "concept" : 概念・方法論候補
      - "company" : 会社候補（v1 ではスコープ外として除外される）
      - "path"    : パス参照（`/` 含む）
      - "meeting" : 議事録・ミーティング参照
      - "unknown" : 判定不能
    """
    # Layer 1: 強い文字列パターン（フィールド context より優先）
    if '/' in link:
        return 'path'
    if _DATE_PREFIX_RE.match(link):
        return 'meeting'
    if _MEETING_SUFFIX_RE.search(link):
        return 'meeting'

    # Layer 2: field コンテキストの多数決
    # FIELD_TO_KIND は concept 系フィールド（topic/topics/frame/framework 等）を含む
    votes: dict[str, int] = {}
    for app in appearances:
        ctx = app.get('context')
        if ctx in FIELD_TO_KIND:
            kind = FIELD_TO_KIND[ctx]
            votes[kind] = votes.get(kind, 0) + 1

    if votes:
        return max(votes.items(), key=lambda x: x[1])[0]

    # Layer 3: 弱パターン（最後の手段）
    if _SLUG_RE.match(link):
        return 'project'
    # 名詞語尾（戦略/方法論/設計 等）は概念ノートのシグナルとして使う
    if _CONCEPT_SUFFIX_RE.search(link):
        return 'concept'
    # 注: 以前はここで「日本語含む = person」と即断していたが廃止。
    # 人物名は通常 participants/members 等のフィールドに現れ Layer 2 で捕捉される。
    # body のみに出現する日本語リンクは概念やその他エンティティである可能性が高い。
    return 'unknown'


def scan(include_company: bool = False, include_path: bool = False,
         include_meeting: bool = False) -> list[dict]:
    """vault 全体から未解決 wikilink を抽出。

    デフォルトでは person / project / unknown のみ返す。
    company / path / meeting は v1 のスコープ外として除外。
    """
    existing = enumerate_all_locations()
    company_names = get_existing_company_names()
    excluded_links = load_excluded_links()

    unresolved: dict[str, list[dict]] = {}

    for md in VAULT_DIR.rglob('*.md'):
        if is_scan_excluded(md):
            continue
        try:
            content = md.read_text(encoding='utf-8')
        except OSError:
            continue

        rel_path = str(md.relative_to(VAULT_DIR))
        for occ in extract_wikilinks(content):
            link = occ['link']
            if link in existing:
                continue
            if link in excluded_links:
                continue
            unresolved.setdefault(link, []).append({
                'file': rel_path,
                'line': occ['line'],
                'context': occ['context'],
            })

    skip_kinds = set()
    if not include_company:
        skip_kinds.add('company')
    if not include_path:
        skip_kinds.add('path')
    if not include_meeting:
        skip_kinds.add('meeting')

    results = []
    for link in sorted(unresolved.keys()):
        appearances = unresolved[link]
        # 既存 03_companies/ にある company 名は完全に除外
        if link in company_names:
            continue

        kind = determine_kind(link, appearances)
        if kind in skip_kinds:
            continue
        results.append({
            'link': link,
            'kind': kind,
            'appearances': appearances,
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pretty', action='store_true', help='整形出力')
    parser.add_argument('--include-company', action='store_true',
                        help='company kind も含める（デバッグ用）')
    parser.add_argument('--include-path', action='store_true',
                        help='path kind も含める（デバッグ用）')
    parser.add_argument('--include-meeting', action='store_true',
                        help='meeting kind も含める（デバッグ用）')
    args = parser.parse_args()

    results = scan(
        include_company=args.include_company,
        include_path=args.include_path,
        include_meeting=args.include_meeting,
    )
    indent = 2 if args.pretty else None
    print(json.dumps(results, ensure_ascii=False, indent=indent))


if __name__ == '__main__':
    main()
