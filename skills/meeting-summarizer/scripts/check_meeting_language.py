#!/usr/bin/env python3
"""
check_meeting_language.py: 04_meetings の議事録本文に英語文が連続していないか簡易検査する。

目的:
  meeting-summarizer が frontmatter/見出しだけ日本語で、本文主要セクションを英語で
  生成してしまう事故を検出する。

検査内容:
  - frontmatter を除いた本文を対象にする
  - 見出し、空行、コードブロック、URLのみの行は除外する
  - ASCII 英字が多く、日本語文字がほぼ無い行を「英語疑い行」とする
  - 英語疑い行が N 行連続したら NG（既定: 2）

注意:
  固有名詞・ツール名・略語（Google Drive, Gemini, Claude, KPI 等）を含む日本語行は
  日本語文字を含むため通常は検出されない。あくまで運用品質ゲート用の簡易チェック。

使用例:
  python3 scripts/check_meeting_language.py ./vault/04_meetings/2026-05-11_xxx.md
  python3 scripts/check_meeting_language.py --all --pretty
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import MEETINGS_DIR, parse_frontmatter

JAPANESE_RE = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
ASCII_ALPHA_RE = re.compile(r'[A-Za-z]')
URL_RE = re.compile(r'^https?://\S+$')


def is_english_like_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(('#', '---', '<!--', '-->')):
        return False
    if stripped.startswith('```'):
        return False
    if URL_RE.match(stripped):
        return False

    japanese_count = len(JAPANESE_RE.findall(stripped))
    alpha_count = len(ASCII_ALPHA_RE.findall(stripped))

    # Markdown 記号・数字だけの行や、英字略語が混じる日本語行は除外する。
    if alpha_count < 12:
        return False
    if japanese_count >= 3:
        return False

    visible_chars = [ch for ch in stripped if not ch.isspace()]
    if not visible_chars:
        return False
    alpha_ratio = alpha_count / len(visible_chars)
    return alpha_ratio >= 0.45


def analyze_file(path: Path, consecutive_threshold: int) -> dict:
    content = path.read_text(encoding='utf-8')
    _fm, body = parse_frontmatter(content)

    flagged_runs: list[dict] = []
    current_run: list[dict] = []
    in_code_block = False

    # 実ファイルの行番号を維持するため content 全体で処理する。
    # frontmatter の終端までは parse_frontmatter 後の body 開始位置から概算する。
    body_start_line = content[: content.find(body)].count('\n') + 1 if body and body in content else 1

    for offset, line in enumerate(body.splitlines(), start=0):
        line_no = body_start_line + offset
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            english_like = False
        elif in_code_block:
            english_like = False
        else:
            english_like = is_english_like_line(line)

        if english_like:
            current_run.append({'line': line_no, 'text': line.strip()})
        else:
            if len(current_run) >= consecutive_threshold:
                flagged_runs.append({'start_line': current_run[0]['line'], 'lines': current_run})
            current_run = []

    if len(current_run) >= consecutive_threshold:
        flagged_runs.append({'start_line': current_run[0]['line'], 'lines': current_run})

    return {
        'path': str(path),
        'ok': not flagged_runs,
        'consecutive_threshold': consecutive_threshold,
        'flagged_runs': flagged_runs,
    }


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    if args.all:
        return sorted(MEETINGS_DIR.glob('*.md'))
    return [Path(p).expanduser() for p in args.paths]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', help='検査する議事録ファイル')
    parser.add_argument('--all', action='store_true', help='04_meetings/*.md をすべて検査')
    parser.add_argument('--threshold', type=int, default=2, help='NG とする英語疑い連続行数（既定: 2）')
    parser.add_argument('--pretty', action='store_true', help='JSON を整形して出力')
    args = parser.parse_args()

    if not args.all and not args.paths:
        parser.error('paths または --all が必要です')

    targets = resolve_targets(args)
    results = []
    for path in targets:
        if not path.exists():
            results.append({'path': str(path), 'ok': False, 'error': 'file not found'})
            continue
        try:
            results.append(analyze_file(path, args.threshold))
        except Exception as exc:  # noqa: BLE001 - 運用チェックなのでファイル単位で継続
            results.append({'path': str(path), 'ok': False, 'error': str(exc)})

    print(json.dumps(results, ensure_ascii=False, indent=2 if args.pretty else None))

    if any(not result.get('ok') for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
