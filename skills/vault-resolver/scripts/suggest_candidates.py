#!/usr/bin/env python3
"""
suggest_candidates.py: 単一 wikilink に対して既存エンティティから類似候補を提案。

判定ロジック:
  - 正規化マッチ（NFKC + 空白除去 + lower）→ confidence 0.95
  - Levenshtein 距離:
      d=0:           0.95
      d=1:           0.85
      d=2:           0.65
      d=3 (and len>4): 0.45
      d>=4:          除外

Project の場合、aliases / name フィールドも比較対象に含める。
ヒット時の表示名は wikilink で書く形（slug）に統一。

入出力:
  --link <未解決リンク>
  --kind person|project
  [--top N]
  [--pretty]
  → JSON 配列
    例:
    [
      { "name": "山田太朗", "confidence": 0.85, "reasons": ["levenshtein:1 via 山田太朗"] },
      ...
    ]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    get_existing_concept_names,
    get_existing_people_names,
    get_existing_project_aliases,
    get_existing_project_slugs,
    levenshtein,
    normalize,
)


def _confidence_for(d: int, length: int) -> float:
    """編集距離 d と max長 length から候補信頼度を算出。

    短文字列での誤マッチを避けるため、length と similarity 両方で閾値判定する:
      - d=0          : 0.95（完全一致）
      - length < 4   : exact 以外は除外（短文字列は曖昧）
      - d=1          : 0.85（typo 相当）
      - d=2 (sim>=.65, len>=5) : 0.65
      - d=3-4 (sim>=.70, len>=6) : 0.45
      - その他       : 除外
    """
    if d == 0:
        return 0.95
    if length < 4:
        return 0.0
    sim = 1.0 - (d / length)
    if d == 1:
        return 0.85
    if d == 2 and sim >= 0.65 and length >= 5:
        return 0.65
    if d <= 4 and sim >= 0.70 and length >= 6:
        return 0.45
    return 0.0


def suggest(link: str, kind: str, top_n: int = 3) -> list[dict]:
    if kind == 'person':
        # 各候補は (表示用 slug, 比較対象 search_key) のペア
        pool = [(name, name) for name in get_existing_people_names()]
    elif kind == 'project':
        pool = [(slug, slug) for slug in get_existing_project_slugs()]
        # name / aliases も比較対象に追加。表示は slug で。
        for alias, slug in get_existing_project_aliases().items():
            pool.append((slug, alias))
    elif kind == 'concept':
        pool = [(name, name) for name in get_existing_concept_names()]
    else:
        return []

    norm_link = normalize(link)

    scored: list[dict] = []
    for slug, search_key in pool:
        norm_key = normalize(search_key)

        if norm_link == norm_key:
            scored.append({
                'name': slug,
                'confidence': 0.95,
                'reasons': [f'normalized_match:{search_key}'],
            })
            continue

        d = levenshtein(norm_link, norm_key)
        conf = _confidence_for(d, max(len(norm_link), len(norm_key)))
        if conf == 0.0:
            continue
        reason = f'levenshtein:{d}'
        if search_key != slug:
            reason += f' via {search_key}'
        scored.append({
            'name': slug,
            'confidence': conf,
            'reasons': [reason],
        })

    # 同じ slug の最高 confidence を残す
    by_name: dict[str, dict] = {}
    for s in scored:
        if s['name'] not in by_name or s['confidence'] > by_name[s['name']]['confidence']:
            by_name[s['name']] = s
        elif s['confidence'] == by_name[s['name']]['confidence']:
            # reason マージ
            by_name[s['name']]['reasons'].extend(s['reasons'])

    return sorted(by_name.values(), key=lambda x: x['confidence'], reverse=True)[:top_n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--link', required=True, help='未解決 wikilink テキスト')
    parser.add_argument('--kind', required=True, choices=['person', 'project', 'concept'])
    parser.add_argument('--top', type=int, default=3)
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args()

    results = suggest(args.link, args.kind, top_n=args.top)
    indent = 2 if args.pretty else None
    print(json.dumps(results, ensure_ascii=False, indent=indent))


if __name__ == '__main__':
    main()
