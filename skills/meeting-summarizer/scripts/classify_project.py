#!/usr/bin/env python3
"""
classify_project.py: 1本のトランスクリプトを client (会社) と project (案件) の
二段で分類する。

二段分類:
  1. client マッチ: 03_companies/<slug>.md の name + aliases を transcript の
     title/body と突き合わせる。title hit なら high、body のみなら medium。
  2. project マッチ: client がマッチしたら、その company の projects: に絞り込んで
     スコアリング。client がマッチしなければ 01_projects/ 全件を対象にする。

出力:
  {
    "client": {
      "slug": "ゴダイ",
      "name": "ゴダイ",
      "confidence": "high" | "medium",
      "matched_via": ["title:ゴダイ"],
      "candidates": [               # 上位 N 件（同点会社・他社が並走するケース用）
        {"slug": "ゴダイ", "score": 40, "matched_via": ["title:ゴダイ"]},
        ...
      ]
    } | null,
    "projects": [
      {
        "project": "godai-ai-training",
        "score": 95,
        "confidence": "high" | "medium" | "low",
        "reasons": ["alias:ゴダイ研修", ...],
        "client": "ゴダイ",
        "operator": "Xenkai",
        "status": "active",
        "scope": "client-filtered" | "all"   # client 絞り込み済みか全件スコアか
      },
      ...
    ]
  }

Project スコアリング（既存ロジック踏襲）:
  - aliases タイトル一致: +40
  - keywords タイトル一致: 5pt × 最大6個 (+30)
  - keywords 本文一致: 3pt × 最大5個 (+15)
  - participant_signatures.required_any 本文一致: 1名+10, 2名以上+20
  - excluded_keywords 一致 (タイトル or 本文): -30
  - participant_signatures.excluded 一致: -30
  - status=active: +5

信頼度:
  - >= 85: high
  - 50-84: medium
  - <50:   low

オプション:
  --transcript PATH   対象ファイル
  --top N             projects 上位N件（デフォルト 3）
  --pretty            整形出力
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    extract_wiki,
    load_companies,
    load_projects,
    parse_frontmatter,
)


# ── Client (Company) マッチ ─────────────────────────────────
def _match_companies(title: str, body: str, companies: list[dict]) -> list[dict]:
    """各 company について alias マッチを取り、ヒットしたものを返す（score 降順）。

    各エントリ:
      {slug, name, score, matched_via, projects}
    matched_via は "title:<alias>" / "body:<alias>" の列。
    title hit があれば +40、body のみなら +15。複数 alias hit は重ねず first match のみ。
    """
    title = title or ''
    body = body or ''

    matched = []
    for c in companies:
        aliases = c.get('_aliases') or []
        title_hit = next((a for a in aliases if a in title), None)
        body_hit = None if title_hit else next((a for a in aliases if a in body), None)

        if not title_hit and not body_hit:
            continue

        if title_hit:
            score = 40
            matched_via = [f'title:{title_hit}']
        else:
            score = 15
            matched_via = [f'body:{body_hit}']

        # project スラッグ列を抽出（wikilink 形式から中身を取り出す）
        project_slugs: list[str] = []
        for p in c.get('projects') or []:
            slug = extract_wiki(p)
            if slug:
                project_slugs.append(slug)

        matched.append({
            'slug': c['_slug'],
            'name': c.get('name') or c['_slug'],
            'score': score,
            'matched_via': matched_via,
            'projects': project_slugs,
        })

    matched.sort(key=lambda x: x['score'], reverse=True)
    return matched


def _client_confidence(score: int) -> str:
    if score >= 40:
        return 'high'
    if score >= 15:
        return 'medium'
    return 'low'


# ── Project スコアリング（既存ロジック） ────────────────────
def _score_project(title: str, body: str, project: dict) -> tuple[int, list[str]]:
    """1 Project に対するスコアと理由を返す。"""
    reasons: list[str] = []
    score = 0

    title = title or ''
    body = body or ''

    # aliases タイトル一致 (+40 once)
    for alias in project.get('aliases') or []:
        if alias and alias in title:
            score += 40
            reasons.append(f'alias:{alias}')
            break

    # keywords タイトル一致 (+5 × max 6)
    kw_title_hits = 0
    for kw in project.get('keywords') or []:
        if kw and kw in title:
            kw_title_hits += 1
            reasons.append(f'kw_title:{kw}')
            if kw_title_hits >= 6:
                break
    score += min(kw_title_hits, 6) * 5

    # keywords 本文一致 (+3 × max 5)
    kw_body_hits = 0
    for kw in project.get('keywords') or []:
        if kw and kw in body:
            kw_body_hits += 1
            reasons.append(f'kw_body:{kw}')
            if kw_body_hits >= 5:
                break
    score += min(kw_body_hits, 5) * 3

    # participant_signatures
    psig = project.get('participant_signatures') or {}
    required = psig.get('required_any') or []
    excluded = psig.get('excluded') or []

    psig_hits = [n for n in required if n and n in body]
    if len(psig_hits) >= 2:
        score += 20
        reasons.append('psig:' + '+'.join(psig_hits[:3]))
    elif len(psig_hits) == 1:
        score += 10
        reasons.append(f'psig:{psig_hits[0]}')

    psig_excl_hits = [n for n in excluded if n and n in body]
    if psig_excl_hits:
        score -= 30
        reasons.append('psig_excl:' + '+'.join(psig_excl_hits[:2]))

    # excluded_keywords
    for ekw in project.get('excluded_keywords') or []:
        if ekw and (ekw in title or ekw in body):
            score -= 30
            reasons.append(f'ekw:{ekw}')
            break

    # status active ボーナス
    if project.get('status') == 'active':
        score += 5
        reasons.append('active')

    return score, reasons


def _project_confidence(score: int) -> str:
    if score >= 85:
        return 'high'
    if score >= 50:
        return 'medium'
    return 'low'


# ── 二段分類 ────────────────────────────────────────────────
def classify(transcript_path: Path, top_n: int = 3) -> dict:
    fm, body = parse_frontmatter(transcript_path.read_text(encoding='utf-8'))
    title = str(fm.get('title', ''))

    # ── Stage 1: client マッチ ──
    companies = load_companies()
    client_matches = _match_companies(title, body, companies)

    client: dict | None = None
    client_project_slugs: set[str] | None = None
    if client_matches:
        top = client_matches[0]
        client = {
            'slug': top['slug'],
            'name': top['name'],
            'confidence': _client_confidence(top['score']),
            'matched_via': top['matched_via'],
            'candidates': [
                {'slug': m['slug'], 'score': m['score'], 'matched_via': m['matched_via']}
                for m in client_matches[:top_n]
            ],
        }
        # client が project リストを持っていれば、その slug 集合で project を絞る
        if top['projects']:
            client_project_slugs = set(top['projects'])

    # ── Stage 2: project スコアリング ──
    projects = load_projects(active_only=False)

    if client_project_slugs:
        scoped_projects = [p for p in projects if p['_slug'] in client_project_slugs]
        scope = 'client-filtered'
        # 絞り込み後が空になったケース（company の projects: リストが古い等）は
        # 全件スコアにフォールバック
        if not scoped_projects:
            scoped_projects = projects
            scope = 'all'
    else:
        scoped_projects = projects
        scope = 'all'

    scored: list[dict] = []
    for proj in scoped_projects:
        score, reasons = _score_project(title, body, proj)
        if score <= 0:
            continue
        scored.append({
            'project': proj['_slug'],
            'score': score,
            'confidence': _project_confidence(score),
            'reasons': reasons,
            'client': extract_wiki(proj.get('client')) or '',
            'operator': extract_wiki(proj.get('operator')) or '',
            'status': proj.get('status') or '',
            'scope': scope,
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return {
        'client': client,
        'projects': scored[:top_n],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transcript', required=True, help='対象トランスクリプトのパス')
    parser.add_argument('--top', type=int, default=3, help='projects 上位N件（デフォルト 3）')
    parser.add_argument('--pretty', action='store_true', help='整形出力')
    args = parser.parse_args()

    path = Path(args.transcript).expanduser().resolve()
    if not path.exists():
        print(json.dumps({'error': f'file not found: {path}'}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    result = classify(path, top_n=args.top)
    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == '__main__':
    main()
