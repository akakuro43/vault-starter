#!/usr/bin/env python3
"""
migrate_to_dir.py: 02_people/<name>.md を 02_people/<name>/<name>.md + observations.md
の per-person directory 構造に移行する。

  Before:                              After:
  02_people/                           02_people/
  ├── 渡邉隆.md       ← all in one     ├── 渡邉隆/
  ├── 関根清志郎.md                       │   ├── 渡邉隆.md         ← profile + 基本情報 + 参加履歴
  └── ...                              │   └── observations.md   ← 観察ログのみ
                                       ├── 関根清志郎/...
                                       └── ...

処理:
  各 02_people/*.md（type: person のみ）について:
    1. 元ファイルを読む
    2. body から `## 観察ログ` セクションを抜き出す
    3. ホームノート用 body から `## 観察ログ` を除去
    4. mkdir 02_people/<name>/
    5. mv 02_people/<name>.md → 02_people/<name>/<name>.md（観察ログ除去版）
    6. 抜き出した観察ログを 02_people/<name>/observations.md として保存

  - 観察ログが空 / セクションなしの場合: observations.md を雛形（ヘッダのみ）で作成
  - type: person 以外の md は触らない（map.md, index.md など）
  - 既に <name>/<name>.md が存在する場合: skip（再実行安全）

オプション:
  --dry-run   実行内容を表示するだけで書き込まない
  --pretty    詳細表示
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    PEOPLE_DIR,
    find_section_bounds,
    parse_frontmatter,
)


# ── 観察ログ抜き出し ─────────────────────────────────────────
def _extract_obs_section(body: str) -> tuple[str, str]:
    """body から `## 観察ログ` セクションを抜き出す。

    Returns: (observations_section, body_without_observations)
      - observations_section: `## 観察ログ\n\n...` の完全なセクション文字列。無ければ ''
      - body_without_observations: 観察ログを除去した body
    """
    bounds = find_section_bounds(body, '観察ログ')
    if not bounds:
        return '', body
    start, end = bounds
    obs = body[start:end].rstrip()
    # 直前の余分な空行を削除（過剰な空白を避ける）
    pre_start = start
    while pre_start > 0 and body[pre_start - 1] == '\n':
        pre_start -= 1
    new_body = body[:pre_start] + ('\n' if body[end:].lstrip('\n') else '') + body[end:].lstrip('\n')
    return obs, new_body


# ── observations.md 作成 ─────────────────────────────────────
_OBS_HEADER_TEMPLATE = """\
---
type: observations
person: "{name}"
---

# {name} 観察ログ

人物の会議観察を時系列で蓄積するノート。person-enricher スキルが自動で append する。
合成時は `02_people/{name}/{name}.md` の `## プロファイル` セクションに反映される。

"""


def _build_observations_file(name: str, obs_section: str) -> str:
    """observations.md の完全な内容を生成する。

    obs_section は `## 観察ログ\n\n### YYYY-MM-DD ...\n...` の形。
    トップヘッダ部分を除いて entries だけ抽出するか、`## 観察ログ` を残すかは
    今回は素直に `## 観察ログ` を残す（互換性確保のため）。
    """
    header = _OBS_HEADER_TEMPLATE.format(name=name)
    if obs_section.strip():
        return header + obs_section.rstrip() + '\n'
    # 観察ログが無いときは雛形だけ
    return header + '## 観察ログ\n\n（まだ観察なし）\n'


# ── 1 人物の移行処理 ─────────────────────────────────────────
def migrate_one(md_path: Path, dry_run: bool = False) -> dict:
    """1 つの 02_people/<name>.md を新構造に移行。

    Returns: 結果サマリ dict
    """
    name = md_path.stem
    new_dir = PEOPLE_DIR / name
    new_home = new_dir / f'{name}.md'

    result: dict = {
        'name': name,
        'status': 'pending',
        'reason': None,
        'obs_entries': 0,
    }

    # 既に新構造が存在 → skip
    if new_home.exists():
        result['status'] = 'skip'
        result['reason'] = 'already migrated'
        return result

    content = md_path.read_text(encoding='utf-8')
    fm, body = parse_frontmatter(content)
    if fm.get('type') != 'person':
        result['status'] = 'skip'
        result['reason'] = f'not type:person (got {fm.get("type")})'
        return result

    obs_section, body_without_obs = _extract_obs_section(body)

    # 観察 entry 数のカウント (### YYYY-MM-DD ... を数える)
    if obs_section:
        result['obs_entries'] = obs_section.count('\n### ')

    # 新しい home content（観察ログ除いた版）
    import re
    fm_match = re.match(r'^(---\n.*?\n---\n?)', content, re.DOTALL)
    if not fm_match:
        result['status'] = 'error'
        result['reason'] = 'no frontmatter delimiter'
        return result
    new_home_content = fm_match.group(1) + body_without_obs

    new_obs_content = _build_observations_file(name, obs_section)

    if dry_run:
        result['status'] = 'would-migrate'
        result['target_home'] = str(new_home)
        result['target_obs'] = str(new_dir / 'observations.md')
        return result

    # 実行
    new_dir.mkdir(parents=True, exist_ok=True)
    new_home.write_text(new_home_content, encoding='utf-8')
    (new_dir / 'observations.md').write_text(new_obs_content, encoding='utf-8')
    md_path.unlink()  # 旧フラットファイル削除

    result['status'] = 'migrated'
    return result


# ── main ────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--pretty', action='store_true')
    parser.add_argument('--person', default=None, help='1 人だけ指定')
    args = parser.parse_args()

    if args.person:
        targets = [PEOPLE_DIR / f'{args.person}.md']
        if not targets[0].exists():
            print(f'error: {targets[0]} not found', file=sys.stderr)
            sys.exit(1)
    else:
        # PEOPLE_DIR 直下の .md のみ（既にディレクトリ化されたものは glob で当たらない）
        targets = sorted(p for p in PEOPLE_DIR.glob('*.md') if p.is_file())

    stats = {'migrated': 0, 'skip': 0, 'error': 0, 'would-migrate': 0}
    for md in targets:
        r = migrate_one(md, dry_run=args.dry_run)
        stats[r['status']] = stats.get(r['status'], 0) + 1
        if args.pretty:
            extras = []
            if r.get('obs_entries'):
                extras.append(f"obs={r['obs_entries']}")
            if r.get('reason'):
                extras.append(r['reason'])
            extra_str = f"  [{', '.join(extras)}]" if extras else ''
            print(f"{r['status']}: {r['name']}{extra_str}")
        else:
            print(f"{r['status']}: {r['name']}")

    summary = f"\nmigrated={stats.get('migrated',0)} would-migrate={stats.get('would-migrate',0)} skip={stats.get('skip',0)} error={stats.get('error',0)} total={len(targets)}"
    if args.dry_run:
        summary += '  [DRY-RUN: no files written]'
    print(summary)


if __name__ == '__main__':
    main()
