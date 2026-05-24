#!/usr/bin/env python3
"""
move_to_processed.py: トランスクリプトを 00_inbox/meeting_transcripts/processed/YYYY-MM/ に退避する。

退避先のサブフォルダはトランスクリプトの frontmatter `date:` を元に決定。
date が読めない場合はファイル名から抽出（例: 2026-05-01_xxx.md → 2026-05）。
それも無理なら今日の年月。

入出力:
  --path PATH
  → 標準出力に "moved: <new_path>" or "noop: already in processed/"
  終了コード: 0=成功, 1=エラー
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import (
    INBOX_TRANSCRIPTS_DIR,
    PROCESSED_DIR,
    parse_frontmatter,
)

_DATE_PREFIX_RE = re.compile(r'^(\d{4})-(\d{2})-\d{2}_')


def _resolve_yyyy_mm(path: Path) -> str:
    # frontmatter の date を優先
    try:
        fm, _ = parse_frontmatter(path.read_text(encoding='utf-8'))
        d = str(fm.get('date') or '')
        if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
            return d[:7]
    except OSError:
        pass

    # ファイル名から抽出
    m = _DATE_PREFIX_RE.match(path.name)
    if m:
        return f'{m.group(1)}-{m.group(2)}'

    # フォールバック: 今日の年月
    return datetime.now().strftime('%Y-%m')


def move(src: Path) -> str:
    src = src.expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f'transcript not found: {src}')

    # 既に processed/ 配下なら no-op
    try:
        src.relative_to(PROCESSED_DIR)
        return f'noop: already in processed: {src}'
    except ValueError:
        pass

    # 退避先が inbox 配下であることを確認（事故防止）
    try:
        src.relative_to(INBOX_TRANSCRIPTS_DIR)
    except ValueError:
        raise ValueError(f'src is not under {INBOX_TRANSCRIPTS_DIR}: {src}')

    yyyy_mm = _resolve_yyyy_mm(src)
    dest_dir = PROCESSED_DIR / yyyy_mm
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    if dest.exists():
        # 衝突回避: ファイル名にサフィックス
        for i in range(2, 100):
            alt = dest_dir / f'{src.stem}_{i}{src.suffix}'
            if not alt.exists():
                dest = alt
                break
        else:
            raise RuntimeError(f'too many name collisions for {src.name}')

    shutil.move(str(src), str(dest))
    return f'moved: {dest}'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', required=True, help='トランスクリプトのパス')
    args = parser.parse_args()

    try:
        msg = move(Path(args.path))
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)
    print(msg)


if __name__ == '__main__':
    main()
