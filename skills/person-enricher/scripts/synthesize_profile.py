#!/usr/bin/env python3
"""
synthesize_profile.py: 02_people/<人物>/<人物>.md の `## プロファイル` セクションを更新する。

LLM が観察ログ (02_people/<人物>/observations.md) から合成した「プロファイル」テキストを
受け取り、決定論的に書き換える。セクションが無ければ「基本情報」直後に挿入。

入力:
  --person <名前>
  --observation-count N        合成元の観察数（記録用）
  --profile-content <text or "-">  プロファイル本文（## ヘッダなし）
                                   - sub-heading（### 役割と立場 等）を含めて記述
                                   - 標準入力からも可

出力: 標準出力に "synthesized: <person>" など
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    get_person_path,
    parse_frontmatter,
    person_exists,
    replace_or_insert_section,
    update_frontmatter_field,
)
import re

JST = timezone(timedelta(hours=9))


def _today() -> str:
    return datetime.now(JST).strftime('%Y-%m-%d')


def synthesize(person: str, profile_body: str, observation_count: int) -> str:
    if not person_exists(person):
        raise FileNotFoundError(f'person not found: 02_people/{person}.md')

    home = get_person_path(person)
    content = home.read_text(encoding='utf-8')
    fm, body = parse_frontmatter(content)
    if fm.get('type') != 'person':
        raise ValueError(f'not a person file: {home}')

    # `## プロファイル` セクションを生成
    header = '## プロファイル'
    meta_line = f'最終更新: {_today()}（観察 {observation_count} 件から合成）'
    new_section = f'{header}\n\n{meta_line}\n\n{profile_body.strip()}\n'

    # 基本情報 の直後に挿入（既にあれば置換）
    new_body = replace_or_insert_section(body, 'プロファイル', new_section, insert_after='基本情報')

    # frontmatter の updated を今日に
    content = update_frontmatter_field(content, 'updated', _today())
    fm2, _ = parse_frontmatter(content)
    fm_match = re.match(r'^(---\n.*?\n---\n)', content, re.DOTALL)
    if not fm_match:
        raise ValueError('frontmatter delimiter lost')
    new_content = fm_match.group(1) + new_body

    home.write_text(new_content, encoding='utf-8')
    return f'synthesized: {person} (from {observation_count} observations)'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--person', required=True)
    parser.add_argument('--observation-count', type=int, required=True)
    parser.add_argument('--profile-content', required=True,
                        help='プロファイル本文（テキスト）または "-" で標準入力')
    args = parser.parse_args()

    if args.profile_content == '-':
        profile_body = sys.stdin.read()
    else:
        profile_body = args.profile_content

    try:
        msg = synthesize(args.person, profile_body, args.observation_count)
    except (FileNotFoundError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)
    print(msg)


if __name__ == '__main__':
    main()
