"""
vault_io: meeting-summarizer スキル共通の Vault I/O ユーティリティ。

責務:
  - frontmatter の読み書き
  - 01_projects/ の Project エンティティ読み込み
  - パスの一元化
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

# ── パス定数 ───────────────────────────────────────────────
# VAULT_PATH 環境変数で上書き可。デフォルトはリポジトリ直下の vault/
VAULT_DIR              = Path(os.environ.get('VAULT_PATH', Path(__file__).resolve().parents[4] / 'vault')).expanduser().resolve()
INBOX_TRANSCRIPTS_DIR  = VAULT_DIR / '00_inbox' / 'meeting_transcripts'
PROCESSED_DIR          = INBOX_TRANSCRIPTS_DIR / 'processed'
MEETINGS_DIR           = VAULT_DIR / '04_meetings'
PROJECTS_DIR           = VAULT_DIR / '01_projects'
COMPANIES_DIR          = VAULT_DIR / '03_companies'


# ── frontmatter ──────────────────────────────────────────
_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n?(.*)$', re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Markdown 文字列から (frontmatter dict, body) を返す。

    frontmatter が無ければ ({}, content) を返す。
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2)


def update_frontmatter_field(content: str, key: str, new_value: str) -> str:
    """frontmatter 内の単一フィールドを書き換える。書き換え後の content を返す。

    既存の YAML 表記（inline list, quote 種類, インデント）と body を保つため、
    yaml.dump で全書きせず、対象行のみを surgical に置換する。
    frontmatter 以外（区切り `---`、本文）は完全に保持される。

    対象キーが存在しない場合は frontmatter の末尾に追加する。
    対象キーがあっても複雑な構造（list/dict）の場合は ValueError。

    new_value は文字列としてそのまま埋め込まれる（数値・日付もOK）。
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        raise ValueError('no frontmatter found')

    fm_text  = m.group(1)
    fm_start = m.start(1)
    fm_end   = m.end(1)

    # 単一行の `key: value` を探す（list/dict は対象外）
    line_re = re.compile(rf'^({re.escape(key)}\s*:)([^\n]*)$', re.MULTILINE)
    line_m = line_re.search(fm_text)

    if line_m:
        # 後続行がインデントされていたら複雑構造とみなして拒否
        end = line_m.end()
        rest = fm_text[end:]
        next_line = rest.lstrip('\n').split('\n', 1)[0] if rest else ''
        if next_line.startswith((' ', '\t', '-')):
            raise ValueError(f'field {key!r} appears to be a complex structure; refusing to update')
        new_fm = fm_text[:line_m.start()] + f'{key}: {new_value}' + fm_text[end:]
    else:
        # 存在しない場合は末尾に追加
        sep = '' if fm_text.endswith('\n') else '\n'
        new_fm = f'{fm_text}{sep}{key}: {new_value}'

    # frontmatter 部分だけ差し替えて、区切り行と body は元のまま保持
    return content[:fm_start] + new_fm + content[fm_end:]


# ── Project エンティティローダ ────────────────────────────
def load_projects(active_only: bool = False) -> list[dict]:
    """01_projects/<slug>/<slug>.md を読み込んで dict のリストで返す。

    各 dict は frontmatter フィールド + 以下のメタを含む:
      - _slug:  ディレクトリ名
      - _path:  ホームノートの絶対パス
      - _body:  本文（frontmatter を除く）

    type: project 以外のファイルは除外する。
    """
    projects = []
    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name in ('archive',):
            continue
        slug = proj_dir.name
        home = proj_dir / f'{slug}.md'
        if not home.exists():
            continue
        fm, body = parse_frontmatter(home.read_text(encoding='utf-8'))
        if fm.get('type') != 'project':
            continue
        if active_only and fm.get('status') != 'active':
            continue
        fm['_slug'] = slug
        fm['_path'] = home
        fm['_body'] = body
        projects.append(fm)
    return projects


def get_project(slug: str) -> Optional[dict]:
    """単一 Project をスラッグで取得。見つからなければ None。"""
    home = PROJECTS_DIR / slug / f'{slug}.md'
    if not home.exists():
        return None
    fm, body = parse_frontmatter(home.read_text(encoding='utf-8'))
    if fm.get('type') != 'project':
        return None
    fm['_slug'] = slug
    fm['_path'] = home
    fm['_body'] = body
    return fm


# ── Company エンティティローダ ────────────────────────────
def load_companies(active_only: bool = False) -> list[dict]:
    """03_companies/<slug>.md を読み込んで dict のリストで返す。

    各 dict は frontmatter フィールド + 以下のメタを含む:
      - _slug:    ファイル名（拡張子なし）
      - _path:    md ファイルの絶対パス
      - _body:    本文（frontmatter を除く）
      - _aliases: name + aliases フィールドを統合した重複除去済みリスト
                  （マッチ用に常に使う列。空文字は除外）

    type: company 以外のファイルは除外する。
    """
    companies = []
    if not COMPANIES_DIR.exists():
        return companies
    for md in sorted(COMPANIES_DIR.glob('*.md')):
        if md.name == 'index.md':
            continue
        fm, body = parse_frontmatter(md.read_text(encoding='utf-8'))
        if fm.get('type') != 'company':
            continue
        if active_only and fm.get('status') != 'active':
            continue

        # name を implicit alias として扱い、aliases と統合
        names = []
        for v in [fm.get('name')] + list(fm.get('aliases') or []):
            if v and isinstance(v, str) and v.strip():
                s = v.strip()
                if s not in names:
                    names.append(s)

        fm['_slug']    = md.stem
        fm['_path']    = md
        fm['_body']    = body
        fm['_aliases'] = names
        companies.append(fm)
    return companies


# ── Wikiリンク抽出 ────────────────────────────────────────
_WIKI_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')


def extract_wiki(value) -> Optional[str]:
    """`"[[ゴダイ]]"` のような wikilink から中身を取り出す。

    list の場合は最初の要素を返す。
    """
    if value is None:
        return None
    if isinstance(value, list):
        for v in value:
            extracted = extract_wiki(v)
            if extracted:
                return extracted
        return None
    m = _WIKI_RE.search(str(value))
    return m.group(1) if m else None
