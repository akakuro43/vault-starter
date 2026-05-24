"""
vault_io: vault-resolver スキル共通の Vault I/O ユーティリティ。

責務:
  - frontmatter の読み出し（surgical 書き込みは v1 では不要）
  - エンティティ列挙（人物・Project・会社）
  - wikilink 抽出（行番号・コンテキスト付き）
  - 文字列正規化・編集距離
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

import yaml

# ── パス定数 ───────────────────────────────────────────────
# VAULT_PATH 環境変数で上書き可。デフォルトはリポジトリ直下の vault/
VAULT_DIR     = Path(os.environ.get('VAULT_PATH', Path(__file__).resolve().parents[4] / 'vault')).expanduser().resolve()
PEOPLE_DIR    = VAULT_DIR / '02_people'
PROJECTS_DIR  = VAULT_DIR / '01_projects'
COMPANIES_DIR = VAULT_DIR / '03_companies'
KNOWLEDGE_DIR = VAULT_DIR / '06_knowledge'

RESOLVER_DIR   = VAULT_DIR / 'ops' / 'resolver'
QUEUE_FILE     = RESOLVER_DIR / 'queue.json'
EXCLUDED_FILE  = RESOLVER_DIR / 'excluded.txt'

# スキャン対象から外すパス（vault からの相対）
# ディレクトリは prefix 一致、単一ファイルは完全一致
EXCLUDED_SCAN_PATHS = [
    '00_inbox',             # 生データ
    'ops',                  # 運用基盤
    '99_system/templates',  # placeholder wikilink を含む
    '.claude',              # Claude Code skill 定義（placeholder だらけ）
    '.agents',              # その他 Agent skill 定義
    'manual',               # Vault マニュアル（プレースホルダー含む）
    'AGENTS.md',            # vault root の Agent ガイド
    'CLAUDE.md',            # vault root の方法論マニュアル（例示 wikilink を含む）
]

# field名 → kind の対応
FIELD_TO_KIND = {
    'participants': 'person',
    'members': 'person',
    'lead': 'person',
    'project': 'project',
    'projects': 'project',
    'client': 'company',
    'operator': 'company',
    'concept': 'concept',
    'topic': 'concept',
    'topics': 'concept',
    'frame': 'concept',
    'framework': 'concept',
}


# 概念ノートらしさを示す名詞語尾パターン（Layer 3 弱パターン用）
# 注: 単漢字 suffix「論」「学」は初版では意図的に除外（誤検出を最小化するため spec §7.2 Q-1）
_CONCEPT_SUFFIX_RE = re.compile(
    r'(戦略|方法論|設計|思考|モデル|フレームワーク|理論|哲学|主義|手法|アプローチ)$'
)

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


# ── エンティティ列挙 ──────────────────────────────────────
def get_existing_people_names() -> set[str]:
    """02_people/ 直下の `type: person` ファイル名（拡張子なし）を返す。"""
    names = set()
    for path in PEOPLE_DIR.glob('*.md'):
        if path.stem in ('index', 'map'):
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding='utf-8'))
            if fm.get('type') == 'person':
                names.add(path.stem)
        except OSError:
            continue
    return names


def get_existing_project_slugs() -> set[str]:
    """01_projects/<slug>/<slug>.md (type: project) の slug を返す。"""
    slugs = set()
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir() or d.name in ('archive',):
            continue
        home = d / f'{d.name}.md'
        if not home.exists():
            continue
        try:
            fm, _ = parse_frontmatter(home.read_text(encoding='utf-8'))
            if fm.get('type') == 'project':
                slugs.add(d.name)
        except OSError:
            continue
    return slugs


def get_existing_project_aliases() -> dict[str, str]:
    """Project の name フィールドや aliases 値を slug にマップする。

    例: {'ゴダイ AI研修': 'godai-ai-training', 'ゴダイ研修': 'godai-ai-training', ...}
    キーが重複した場合は最初に見つかった slug を採用。
    """
    result: dict[str, str] = {}
    for slug in get_existing_project_slugs():
        home = PROJECTS_DIR / slug / f'{slug}.md'
        try:
            fm, _ = parse_frontmatter(home.read_text(encoding='utf-8'))
        except OSError:
            continue
        candidates = []
        if name := fm.get('name'):
            candidates.append(str(name))
        for alias in (fm.get('aliases') or []):
            candidates.append(str(alias))
        for c in candidates:
            result.setdefault(c, slug)
    return result


def get_existing_company_names() -> set[str]:
    """03_companies/ 直下の `type: company` ファイル名（拡張子なし）を返す。"""
    names = set()
    for path in COMPANIES_DIR.glob('*.md'):
        if path.stem in ('index',):
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding='utf-8'))
            if fm.get('type') == 'company':
                names.add(path.stem)
        except OSError:
            continue
    return names


def get_existing_concept_names() -> set[str]:
    """06_knowledge/{insights,frameworks,references}/ 配下の .md ファイル名（拡張子なし）を返す。

    再帰スキャン。index.md / README.md / map.md は除外。
    frontmatter の type フィールドは緩く扱う（無くても concept とみなす）。
    """
    names: set[str] = set()
    _exclude_stems = {'index', 'README', 'map'}
    for subdir in ('insights', 'frameworks', 'references'):
        target = KNOWLEDGE_DIR / subdir
        if not target.is_dir():
            continue
        for path in target.rglob('*.md'):
            if path.stem in _exclude_stems:
                continue
            names.add(path.stem)
    return names


def enumerate_all_locations() -> set[str]:
    """vault 配下の全 .md について解決可能な name のセットを返す。

    Obsidian の wikilink 解決ルールを反映:
      - `[[name]]`         → basename 一致
      - `[[full/path]]`    → vault root からの相対パス一致
      - `[[partial/path]]` → 末尾一致（partial path matching）
      - `[[dir]]`          → 配下に `_index.md` があるディレクトリ名/パス
    """
    result: set[str] = set()
    for p in VAULT_DIR.rglob('*.md'):
        rel = p.relative_to(VAULT_DIR).with_suffix('')
        rel_parts = rel.parts

        # basename
        result.add(p.stem)
        # 完全な相対パス
        result.add(str(rel))
        # 全ての suffix（partial path matching）
        for i in range(1, len(rel_parts)):
            result.add('/'.join(rel_parts[i:]))

        # _index.md は親ディレクトリ名/パスでも解決可能
        if rel.name == '_index' and len(rel_parts) > 1:
            parent_parts = rel_parts[:-1]
            result.add('/'.join(parent_parts))
            for i in range(1, len(parent_parts)):
                result.add('/'.join(parent_parts[i:]))
            result.add(parent_parts[-1])
    return result


# ── wikilink 抽出 ────────────────────────────────────────
_WIKI_RE = re.compile(r'\[\[([^\]|\[]+?)(?:\|[^\]]+)?\]\]')
_FRONTMATTER_DELIMITER = '---'
_FIELD_RE = re.compile(r'^([A-Za-z_][\w-]*):')
_FENCE_RE = re.compile(r'^\s*(```|~~~)')


def extract_wikilinks(content: str) -> list[dict]:
    """Markdown 文字列から wikilink を抽出する。

    各要素は { link, line, context } を持つ。
      - link: wikilink のテキスト（パイプ表記の前、anchor `#section` も除去）
      - line: 行番号（1-indexed）
      - context: frontmatter 内なら直近の field 名、本文なら "body"

    除外:
      - `[[#anchor]]` のような同一ドキュメント内アンカー
      - コードフェンス内（```...``` / ~~~...~~~）
    `[[note#section]]` のような外部ノート anchor 付きリンクは note 部分を採用。
    """
    lines = content.split('\n')
    in_frontmatter = False
    fm_seen_open = False
    in_code_fence = False
    fence_marker: Optional[str] = None
    current_field: Optional[str] = None
    results = []

    for i, line in enumerate(lines, start=1):
        # frontmatter 区切り
        if line.strip() == _FRONTMATTER_DELIMITER:
            if not fm_seen_open:
                fm_seen_open = True
                in_frontmatter = True
                continue
            elif in_frontmatter:
                in_frontmatter = False
                continue

        # body のコードフェンス追跡（frontmatter 内では無視）
        if not in_frontmatter:
            m_fence = _FENCE_RE.match(line)
            if m_fence:
                marker = m_fence.group(1)
                if not in_code_fence:
                    in_code_fence = True
                    fence_marker = marker
                    continue
                elif fence_marker == marker:
                    in_code_fence = False
                    fence_marker = None
                    continue
            if in_code_fence:
                continue  # code fence 内の wikilink は無視

        if in_frontmatter:
            m = _FIELD_RE.match(line)
            if m:
                current_field = m.group(1)

        for match in _WIKI_RE.finditer(line):
            raw = match.group(1).strip()
            if not raw:
                continue
            # anchor 部分を除去（外部ノート anchor 付きリンクは note 部分が target）
            link = raw.split('#', 1)[0].strip()
            # 同一ドキュメント内 anchor `[[#xxx]]` は target 不在なので除外
            if not link:
                continue
            ctx = (current_field or 'frontmatter') if in_frontmatter else 'body'
            results.append({
                'link': link,
                'line': i,
                'context': ctx,
            })

    return results


# ── 文字列正規化・編集距離 ────────────────────────────────
def normalize(s: str) -> str:
    """正規化: NFKC（全角半角統一）→ 空白除去 → lower-case。"""
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', '', s)
    return s.lower()


def levenshtein(a: str, b: str) -> int:
    """編集距離（純Python実装）。"""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        ca = a[i - 1]
        for j in range(1, n + 1):
            cb = b[j - 1]
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
        prev = curr
    return prev[n]


# ── 除外リスト ─────────────────────────────────────────
def load_excluded_links() -> set[str]:
    """ops/resolver/excluded.txt を読み込んで除外リンクのセットを返す。

    1行1リンク。# で始まる行はコメント。空行は無視。
    """
    if not EXCLUDED_FILE.exists():
        return set()
    result = set()
    for line in EXCLUDED_FILE.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        result.add(s)
    return result


# ── スキャン対象判定 ───────────────────────────────────
def is_scan_excluded(path: Path) -> bool:
    """vault 内の path がスキャン対象から除外されているか判定。

    EXCLUDED_SCAN_PATHS の各エントリは：
      - 単一ファイル指定（"AGENTS.md"）: 完全一致
      - ディレクトリ指定（"00_inbox" や ".claude"）: prefix 一致
    """
    try:
        rel = path.relative_to(VAULT_DIR)
    except ValueError:
        return True
    rel_str = str(rel)
    parts = rel.parts
    for ex in EXCLUDED_SCAN_PATHS:
        if rel_str == ex:
            return True
        ex_parts = tuple(ex.split('/'))
        if parts[:len(ex_parts)] == ex_parts:
            return True
    return False
