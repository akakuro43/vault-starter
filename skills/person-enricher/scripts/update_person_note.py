#!/usr/bin/env python3
"""
update_person_note.py: 02_people/<人物>/ 配下を構造化更新する。

  ホームノート (02_people/<人物>/<人物>.md) の更新:
    1. frontmatter の `meeting_count` をインクリメント
    2. frontmatter の `last_meeting` を会議日に更新（より新しい場合のみ）
    3. frontmatter の `updated` を今日の日付に
    4. frontmatter の `related_projects` に議事録の project を union 追加（unclassified は除外）
    5. `## 参加したミーティング` セクションのリストに新しい行を append（無ければ作成）
    6. 「基本情報」table の MTG参加数 / 最終MTG / 関連PJ セルも更新（パターン一致時）

  観察ログ (02_people/<人物>/observations.md) の更新:
    7. `## 観察ログ` セクションに新しいエントリを append（ファイル・セクション無ければ自動作成）

LLM 抽出済みの観察データを JSON で受け取り、決定論的に書き換える。

入力:
  --person <名前>
  --meeting-date YYYY-MM-DD
  --meeting-title "..."
  --meeting-link "[[2026-05-01_xxx]]"   # 参加したミーティング section に書く形
  --meeting-project <project>            # "[[slug]]" / "[[a]],[[b]]" / "unclassified" / 省略可
  --observation-json <JSON文字列 or "-" 標準入力>

observation JSON のスキーマ:
  {
    "key_statements": ["...", ...],   # 発言の要点（必須）
    "interests": ["...", ...],        # 関心
    "role": "提案者",                 # 役割
    "issues_raised": ["...", ...],    # 発した課題感
    "relations": ["...", ...],        # 他者との関係観察（任意・空配列可）
    "expertise_signals": ["...", ...] # 専門性の現れ（任意）
  }

出力: 標準出力に "updated: <person>" or "noop: <reason>"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    find_section_bounds,
    get_observations_path,
    get_person_path,
    parse_frontmatter,
    person_exists,
    replace_or_insert_section,
    update_frontmatter_field,
)

JST = timezone(timedelta(hours=9))

_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n?(.*)$', re.DOTALL)
_RELATED_PROJECTS_BLOCK_RE = re.compile(
    r'^related_projects\s*:[^\n]*(?:\n(?:[ \t]+[^\n]*|-[^\n]*))*\n?',
    re.MULTILINE,
)


def _today() -> str:
    return datetime.now(JST).strftime('%Y-%m-%d')


def _parse_meeting_project(raw: str | None) -> list[str]:
    """`--meeting-project` の引数値から有効な `[[slug]]` 列を抽出。

    `unclassified` / 空文字 / None は除外。カンマ区切り対応。
    """
    if not raw:
        return []
    out: list[str] = []
    for chunk in raw.split(','):
        s = chunk.strip()
        if not s or s.lower() == 'unclassified':
            continue
        # `[[slug]]` 形式に正規化
        m = re.search(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', s)
        if m:
            out.append(f'[[{m.group(1).strip()}]]')
        else:
            # 裸の slug が来たら `[[...]]` で包む
            out.append(f'[[{s}]]')
    return out


def _serialize_inline_list(items: list[str]) -> str:
    """`['[[a]]', '[[b]]']` 形式の inline YAML list 文字列を返す。"""
    if not items:
        return '[]'
    return '[' + ', '.join(f"'{v}'" if "'" not in v else f'"{v}"' for v in items) + ']'


def _update_related_projects_field(content: str, new_projects: list[str]) -> str:
    """frontmatter の related_projects に new_projects を union 追加して書き換える。

    既存値を保持し、順序保ち重複排除。inline list として書き込む。
    new_projects が空なら no-op。
    """
    if not new_projects:
        return content

    m = _FRONTMATTER_RE.match(content)
    if not m:
        raise ValueError('no frontmatter found')

    fm_text  = m.group(1)
    fm_start = m.start(1)
    fm_end   = m.end(1)

    # 現在値の取得（yaml.safe_load を一度通して dict 化）
    try:
        fm_dict = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm_dict = {}
    current = fm_dict.get('related_projects') or []
    if isinstance(current, str):
        current = [current]
    if not isinstance(current, list):
        current = []

    # 既存値を `[[slug]]` 形式に正規化（裸の文字列も来うる）
    normalized: list[str] = []
    for v in list(current) + list(new_projects):
        s = str(v).strip()
        if not s or s.lower() == 'unclassified':
            continue
        wiki_m = re.search(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', s)
        wrapped = f'[[{wiki_m.group(1).strip()}]]' if wiki_m else f'[[{s}]]'
        if wrapped not in normalized:
            normalized.append(wrapped)

    inline = _serialize_inline_list(normalized)
    new_line = f'related_projects: {inline}\n'

    # 既存 related_projects 行（および block 形式の継続行）を置換、無ければ末尾追加
    if _RELATED_PROJECTS_BLOCK_RE.search(fm_text):
        new_fm = _RELATED_PROJECTS_BLOCK_RE.sub(new_line, fm_text, count=1)
    else:
        sep = '' if fm_text.endswith('\n') else '\n'
        new_fm = fm_text + sep + new_line.rstrip('\n')

    return content[:fm_start] + new_fm + content[fm_end:]


def _format_observation_entry(meeting_date: str, meeting_link: str, obs: dict) -> str:
    """観察ログ entry を Markdown 文字列に整形。"""
    lines = [f'### {meeting_date} {meeting_link}', '']

    # 必須項目
    if obs.get('key_statements'):
        lines.append('- **発言の要点**:')
        for s in obs['key_statements']:
            lines.append(f'    - {s}')
    if obs.get('interests'):
        lines.append(f'- **関心**: {", ".join(obs["interests"])}')
    if obs.get('role'):
        lines.append(f'- **役割**: {obs["role"]}')
    if obs.get('issues_raised'):
        lines.append('- **発した課題感**:')
        for s in obs['issues_raised']:
            lines.append(f'    - {s}')

    # 任意項目
    if obs.get('relations'):
        lines.append('- **他者との関係観察**:')
        for s in obs['relations']:
            lines.append(f'    - {s}')
    if obs.get('expertise_signals'):
        lines.append('- **専門性の現れ**:')
        for s in obs['expertise_signals']:
            lines.append(f'    - {s}')

    lines.append('')  # entry 末尾の空行
    return '\n'.join(lines)


def _append_to_section(body: str, header: str, new_entry: str,
                       insert_after: str = '基本情報') -> str:
    """セクションが既にあれば末尾に append、無ければ作成して指定位置に挿入。"""
    bounds = find_section_bounds(body, header)
    if bounds:
        start, end = bounds
        existing = body[start:end].rstrip()
        # ヘッダ行直後に追加するのではなく、既存内容の後に追加
        new_section = existing + '\n\n' + new_entry.rstrip() + '\n'
        return body[:start] + new_section + ('\n' if not body[end:].startswith('\n') else '') + body[end:]
    else:
        new_section = f'## {header}\n\n{new_entry.rstrip()}\n'
        return replace_or_insert_section(body, header, new_section, insert_after=insert_after)


def _update_basic_info_table(body: str, meeting_count: int, last_meeting: str,
                             related_projects: list[str] | None = None) -> str:
    """「基本情報」table 内の MTG参加数 / 最終MTG / 関連PJ セルを更新。

    存在しない場合・パターン不一致は no-op。
    related_projects は `[[slug]]` 形式の list を想定。None なら 関連PJ は触らない。
    """
    body = re.sub(
        r'(\|\s*MTG参加数\s*\|\s*)(\d+件|不明|-)(\s*\|)',
        rf'\g<1>{meeting_count}件\g<3>',
        body,
    )
    body = re.sub(
        r'(\|\s*最終MTG\s*\|\s*)([\d-]+|不明|-|\(なし\))(\s*\|)',
        rf'\g<1>{last_meeting}\g<3>',
        body,
    )
    if related_projects is not None:
        cell_value = ', '.join(related_projects) if related_projects else '-'
        body = re.sub(
            r'(\|\s*関連PJ\s*\|\s*)([^|\n]*?)(\s*\|)',
            rf'\g<1>{cell_value}\g<3>',
            body,
        )
    return body


def _update_meetings_section_header(body: str, meeting_count: int) -> str:
    """`## 参加したミーティング（N件）` の N を更新。

    `## 参加したミーティング` セクション（カウント表記なし）にも対応する。
    """
    return re.sub(
        r'(^##\s+参加したミーティング)(?:（\d+件）)?',
        rf'\g<1>（{meeting_count}件）',
        body,
        count=1,
        flags=re.MULTILINE,
    )


def update(person: str, meeting_date: str, meeting_title: str,
           meeting_link: str, obs: dict,
           meeting_project: str | None = None) -> str:
    if not person_exists(person):
        raise FileNotFoundError(f'person not found: 02_people/{person}.md')

    home = get_person_path(person)
    content = home.read_text(encoding='utf-8')
    fm, body = parse_frontmatter(content)
    if fm.get('type') != 'person':
        raise ValueError(f'not a person file: {home}')

    # frontmatter 更新
    current_count = int(fm.get('meeting_count') or 0)
    new_count = current_count + 1

    current_last = str(fm.get('last_meeting') or '')
    new_last = meeting_date if (not current_last or meeting_date > current_last) else current_last

    content = update_frontmatter_field(content, 'meeting_count', str(new_count))
    content = update_frontmatter_field(content, 'last_meeting', new_last)
    content = update_frontmatter_field(content, 'updated', _today())

    # related_projects に議事録の project を union 追加
    new_projects = _parse_meeting_project(meeting_project)
    if new_projects:
        content = _update_related_projects_field(content, new_projects)

    # 更新後の related_projects（基本情報 table セル更新用）を再取得
    fm_after, _ = parse_frontmatter(content)
    related_for_table: list[str] | None = None
    if new_projects:
        rp = fm_after.get('related_projects') or []
        if isinstance(rp, str):
            rp = [rp]
        related_for_table = [str(v) for v in rp if v]

    # body 部分の更新
    fm2, body2 = parse_frontmatter(content)

    # 基本情報 table のセル更新（関連PJ は new_projects があるときのみ反映）
    body2 = _update_basic_info_table(body2, new_count, new_last,
                                     related_projects=related_for_table)

    # 参加したミーティング リストに 1 行追加 + section header の count を更新
    mtg_line = f'- {meeting_link} ({meeting_date}) — {meeting_title}'
    body2 = _append_to_section(body2, '参加したミーティング', mtg_line, insert_after='基本情報')
    body2 = _update_meetings_section_header(body2, new_count)

    # 再構成
    fm_match = re.match(r'^(---\n.*?\n---\n)', content, re.DOTALL)
    if not fm_match:
        raise ValueError('frontmatter delimiter lost during update')
    new_content = fm_match.group(1) + body2

    home.write_text(new_content, encoding='utf-8')

    # 観察ログは別ファイル observations.md に append（新構造、2026-05-24 〜）
    obs_entry = _format_observation_entry(meeting_date, meeting_link, obs)
    _append_observation_to_file(person, obs_entry)

    return f'updated: {person} (count {current_count} -> {new_count}, last {current_last or "(none)"} -> {new_last})'


def _append_observation_to_file(person: str, obs_entry: str) -> None:
    """02_people/<person>/observations.md に観察 entry を append。

    ファイルが無ければ雛形を作って append、あれば末尾に追記。
    `## 観察ログ` セクションの末尾（あれば）または、ファイル末尾に entry を足す。
    """
    obs_path = get_observations_path(person)
    obs_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        '---\n'
        'type: observations\n'
        f'person: "{person}"\n'
        '---\n\n'
        f'# {person} 観察ログ\n\n'
        '人物の会議観察を時系列で蓄積するノート。person-enricher スキルが自動で append する。\n'
        f'合成時は `02_people/{person}/{person}.md` の `## プロファイル` セクションに反映される。\n\n'
        '## 観察ログ\n\n'
    )

    if not obs_path.exists():
        obs_path.write_text(header + obs_entry.rstrip() + '\n', encoding='utf-8')
        return

    existing = obs_path.read_text(encoding='utf-8')
    # 既存ファイルに `## 観察ログ` があれば末尾に append、なければファイル末尾
    bounds = find_section_bounds(existing, '観察ログ')
    if bounds:
        start, end = bounds
        current = existing[start:end].rstrip()
        new_section = current + '\n\n' + obs_entry.rstrip() + '\n'
        new_content = existing[:start] + new_section + ('\n' if not existing[end:].startswith('\n') else '') + existing[end:]
    else:
        sep = '' if existing.endswith('\n\n') else ('\n' if existing.endswith('\n') else '\n\n')
        new_content = existing + sep + '## 観察ログ\n\n' + obs_entry.rstrip() + '\n'

    obs_path.write_text(new_content, encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--person', required=True)
    parser.add_argument('--meeting-date', required=True)
    parser.add_argument('--meeting-title', required=True)
    parser.add_argument('--meeting-link', required=True,
                        help='例: "[[2026-05-01_xxx]]"')
    parser.add_argument('--meeting-project', default=None,
                        help='例: "[[godai-ai-training]]" / "[[a]],[[b]]" / "unclassified"。'
                             '指定があれば frontmatter.related_projects に union 追加')
    parser.add_argument('--observation-json', required=True,
                        help='JSON 文字列または "-" で標準入力')
    args = parser.parse_args()

    raw = sys.stdin.read() if args.observation_json == '-' else args.observation_json
    obs = json.loads(raw)

    try:
        msg = update(
            person=args.person,
            meeting_date=args.meeting_date,
            meeting_title=args.meeting_title,
            meeting_link=args.meeting_link,
            obs=obs,
            meeting_project=args.meeting_project,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)
    print(msg)


if __name__ == '__main__':
    main()
