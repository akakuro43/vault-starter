"""
vault_io: person-enricher スキル共通の Vault I/O ユーティリティ。

責務:
  - frontmatter の読み出し / surgical 単一フィールド書き換え
  - meeting note からの participants 抽出（新形式 frontmatter 必須）
  - 02_people/<人物>.md のセクション特定・書き換え
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

# ── パス定数 ───────────────────────────────────────────────
# VAULT_PATH 環境変数で上書き可。デフォルトはリポジトリ直下の vault/
VAULT_DIR             = Path(os.environ.get('VAULT_PATH', Path(__file__).resolve().parents[4] / 'vault')).expanduser().resolve()
MEETINGS_DIR          = VAULT_DIR / '04_meetings'
PEOPLE_DIR            = VAULT_DIR / '02_people'
PROCESSED_TRANS_DIR   = VAULT_DIR / '00_inbox' / 'meeting_transcripts' / 'processed'

ENRICHER_DIR  = VAULT_DIR / 'ops' / 'person-enricher'
STATE_FILE    = ENRICHER_DIR / 'state.json'


# ── frontmatter ──────────────────────────────────────────
_FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n?(.*)$', re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Markdown 文字列から (frontmatter dict, body) を返す。"""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2)


def update_frontmatter_field(content: str, key: str, new_value: str) -> str:
    """frontmatter の単一フィールドを surgical に書き換える。

    既存 YAML の表記を保持。複雑な構造（list/dict）は書き換え不可。
    対象キーが存在しない場合は frontmatter 末尾に追加。
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        raise ValueError('no frontmatter found')

    fm_text  = m.group(1)
    fm_start = m.start(1)
    fm_end   = m.end(1)

    line_re = re.compile(rf'^({re.escape(key)}\s*:)([^\n]*)$', re.MULTILINE)
    line_m = line_re.search(fm_text)

    if line_m:
        end = line_m.end()
        rest = fm_text[end:]
        next_line = rest.lstrip('\n').split('\n', 1)[0] if rest else ''
        if next_line.startswith((' ', '\t', '-')):
            raise ValueError(f'field {key!r} appears to be a complex structure; refusing to update')
        new_fm = fm_text[:line_m.start()] + f'{key}: {new_value}' + fm_text[end:]
    else:
        sep = '' if fm_text.endswith('\n') else '\n'
        new_fm = f'{fm_text}{sep}{key}: {new_value}'

    return content[:fm_start] + new_fm + content[fm_end:]


# ── meeting からの participants 抽出 ─────────────────────
_WIKI_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')


def extract_participants_from_meeting(content: str) -> list[str]:
    """meeting note の frontmatter `participants:` から wikilink テキストを抽出。

    新形式（meeting-summarizer 由来）のみ対象。旧形式（plain text 参加者）には
    対応しない。frontmatter に participants が無い／空の場合は [] を返す。
    """
    fm, _ = parse_frontmatter(content)
    raw = fm.get('participants')
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    names = []
    for item in raw:
        if not item:
            continue
        m = _WIKI_RE.search(str(item))
        if m:
            names.append(m.group(1).strip())
    return names


def get_meeting_metadata(meeting_path: Path) -> dict:
    """meeting note から metadata を返す。

    含まれる field: path, date, title, participants, transcript, project, client
    """
    content = meeting_path.read_text(encoding='utf-8')
    fm, _ = parse_frontmatter(content)
    return {
        'path': str(meeting_path),
        'date': str(fm.get('date', '')),
        'title': str(fm.get('title', '')),
        'participants': extract_participants_from_meeting(content),
        'transcript': str(fm.get('transcript', '')),
        'project': fm.get('project'),
        'client': fm.get('client'),
    }


# ── person ノートのセクション操作 ────────────────────────
_SECTION_RE = re.compile(r'^(## .+?)$', re.MULTILINE)


def find_section_bounds(body: str, header: str) -> Optional[tuple[int, int]]:
    """body 内で `## <header>` セクションの (start, end) を返す。

    end は次の `## ` ヘッダ直前、または body 末尾。
    見つからなければ None。
    """
    pattern = re.compile(
        rf'^(##\s+{re.escape(header)}.*?)$',
        re.MULTILINE,
    )
    m = pattern.search(body)
    if not m:
        return None
    start = m.start()
    # 次の ## セクション開始を探す
    next_section = _SECTION_RE.search(body, m.end())
    end = next_section.start() if next_section else len(body)
    return (start, end)


def replace_or_insert_section(body: str, header: str, new_content: str,
                               insert_after: Optional[str] = None) -> str:
    """body 内の `## <header>` セクションを new_content に置換する。

    無い場合:
      - insert_after が指定されていればその直後に挿入
      - そうでなければ body 末尾に追加

    new_content は `## <header>\n...\n` の完全なセクション文字列。
    セクション間には blank line を確保する。
    """
    if not new_content.endswith('\n'):
        new_content += '\n'

    bounds = find_section_bounds(body, header)
    if bounds:
        start, end = bounds
        return body[:start] + new_content + body[end:]

    # 新規挿入
    if insert_after:
        after_bounds = find_section_bounds(body, insert_after)
        if after_bounds:
            _, after_end = after_bounds
            # 前側の separator: 直前で blank line 確保
            sep_before = '' if body[:after_end].endswith('\n\n') else '\n'
            # 後側の separator: 次セクション直前で blank line 確保
            tail = body[after_end:]
            sep_after = '' if (tail == '' or tail.startswith('\n')) else '\n'
            return body[:after_end] + sep_before + new_content + sep_after + tail
    # 末尾追加
    sep = '' if body.endswith('\n\n') else ('\n' if body.endswith('\n') else '\n\n')
    return body + sep + new_content


def get_section_content(body: str, header: str) -> Optional[str]:
    """`## <header>` セクション全体（ヘッダ含む）の文字列を返す。無ければ None。"""
    bounds = find_section_bounds(body, header)
    if not bounds:
        return None
    start, end = bounds
    return body[start:end]


# ── 02_people/ エンティティ確認 ───────────────────────────
# 構造（2026-05-24 以降）:
#   02_people/<name>/<name>.md           ホームノート（基本情報 + プロファイル + 参加履歴）
#   02_people/<name>/observations.md     観察ログ（時系列 append）
#
# 旧構造（互換用フォールバック）:
#   02_people/<name>.md                  すべて 1 ファイルに混在
def person_exists(name: str) -> bool:
    """02_people/<name>/<name>.md (新) または 02_people/<name>.md (旧) が存在するか。"""
    return get_person_path(name).exists()


def get_person_path(name: str) -> Path:
    """ホームノートのパスを返す。

    新構造を優先、旧構造（フラット）も読めるようフォールバックする。
    新規作成時のパスは常に新構造を返す（旧構造は読み取り互換のみ）。
    """
    new_path = PEOPLE_DIR / name / f'{name}.md'
    if new_path.exists():
        return new_path
    legacy = PEOPLE_DIR / f'{name}.md'
    if legacy.exists():
        return legacy
    # どちらも存在しないときは新構造のパスを返す（呼び出し側で exists() チェック）
    return new_path


def get_observations_path(name: str) -> Path:
    """観察ログファイルのパスを返す（新構造のみ）。

    02_people/<name>/observations.md を返す。ホームノートが新構造でなくても、
    観察ログは常に新構造側に書く（migration 後の正準位置）。
    """
    return PEOPLE_DIR / name / 'observations.md'


def get_person_dir(name: str) -> Path:
    """人物ディレクトリ 02_people/<name>/ を返す。"""
    return PEOPLE_DIR / name
