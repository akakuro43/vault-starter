#!/usr/bin/env python3
"""
cleanup_misclassified.py: queue.json の誤分類 pending を再判定し dismiss する。

既存の pending エントリに対して determine_kind() を再実行し、
old kind と new kind が異なるエントリを「誤分類」として検出する。

デフォルトは dry-run（queue.json を変更しない）。
--apply を指定すると誤分類エントリを dismissed[] に移動する。

使い方:
  # dry-run（デフォルト）
  python3 cleanup_misclassified.py --pretty

  # 実書き込み（事前に queue.json.bak が作成される）
  python3 cleanup_misclassified.py --apply --pretty

オプション:
  --queue-path PATH   queue.json パスをオーバーライド（デフォルト: ops/resolver/queue.json）
  --apply             実際に queue.json を変更する（指定なしは dry-run）
  --reason TEXT       dismiss 理由（デフォルト: auto-dismiss: misclassified by old determine_kind）
  --pretty            整形出力

注意:
  --apply は **不可逆** 操作。誤って dismiss したエントリを pending に戻すには手動で
  queue.json を編集する必要がある。安全のため --apply 時は queue.json.bak を自動作成する。
  問題が起きたら mv queue.json.bak queue.json で復元可能。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# scan_unresolved から determine_kind をインポート
sys.path.insert(0, str(Path(__file__).parent))
from scan_unresolved import determine_kind

from lib.vault_io import QUEUE_FILE

JST = timezone(timedelta(hours=9))
DEFAULT_REASON = 'auto-dismiss: misclassified by old determine_kind'


def _now_iso() -> str:
    """現在時刻を ISO8601+09:00 で返す。"""
    return datetime.now(JST).isoformat(timespec='seconds')


def load_queue(queue_path: Path) -> dict:
    """queue.json を読み込む。存在しない場合は空の queue を返す。"""
    if not queue_path.exists():
        raise FileNotFoundError(f'queue.json が見つかりません: {queue_path}')
    return json.loads(queue_path.read_text(encoding='utf-8'))


def save_queue_atomic(queue_path: Path, q: dict) -> None:
    """queue.json を一時ファイル経由でアトミックに書き込む。"""
    tmp_path = queue_path.with_suffix('.json.tmp')
    q['updated_at'] = _now_iso()
    tmp_path.write_text(
        json.dumps(q, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    os.replace(tmp_path, queue_path)


def detect_misclassified(pending: list[dict]) -> list[dict]:
    """pending エントリのうち、determine_kind が old_kind と異なるものを返す。

    戻り値の各要素は元のエントリに new_kind を付加した dict。
    """
    misclassified = []
    for entry in pending:
        link = entry.get('link', '')
        appearances = entry.get('appearances', [])
        old_kind = entry.get('kind', 'unknown')
        new_kind = determine_kind(link, appearances)
        if new_kind != old_kind:
            misclassified.append({
                **entry,
                'new_kind': new_kind,
            })
    return misclassified


def print_summary(
    *,
    total_before: int,
    misclassified: list[dict],
    apply: bool,
    pretty: bool,
) -> None:
    """サマリーを stdout に出力する。"""
    total_after = total_before - len(misclassified)

    if pretty:
        print(f'pending (before): {total_before}')
        print(f'misclassified   : {len(misclassified)}')
        print()
        if misclassified:
            # ヘッダー
            col_link = max(len(e['link']) for e in misclassified)
            col_link = max(col_link, 4)  # 最低 "link" の幅
            col_kind = 9  # "old_kind" の幅
            print(f'  {"link":<{col_link}}  {"old_kind":<{col_kind}}  {"new_kind":<9}  appearances')
            print(f'  {"-" * col_link}  {"-" * col_kind}  {"-" * 9}  -----------')
            for e in misclassified:
                apps_count = len(e.get('appearances', []))
                print(
                    f'  {e["link"]:<{col_link}}'
                    f'  {e["kind"]:<{col_kind}}'
                    f'  {e["new_kind"]:<9}'
                    f'  {apps_count}'
                )
        else:
            print('  (誤分類なし)')
        print()
        if apply:
            print(f'pending (after) : {total_after}')
        else:
            print(f'would-be pending: {total_after}')
            print()
            print('DRY-RUN: no changes written')
    else:
        # compact 出力
        summary = {
            'total_before': total_before,
            'misclassified': len(misclassified),
            'diffs': [
                {
                    'link': e['link'],
                    'old_kind': e['kind'],
                    'new_kind': e['new_kind'],
                    'appearances': len(e.get('appearances', [])),
                }
                for e in misclassified
            ],
        }
        if apply:
            summary['total_after'] = total_after
        else:
            summary['would_be_pending'] = total_after
            summary['dry_run'] = True
        print(json.dumps(summary, ensure_ascii=False))


def apply_cleanup(
    queue_path: Path,
    q: dict,
    misclassified: list[dict],
    reason: str,
) -> None:
    """誤分類エントリを pending から dismissed に移動して保存する。"""
    misclassified_ids = {e['id'] for e in misclassified}
    new_kind_map = {e['id']: e['new_kind'] for e in misclassified}

    # pending から除外
    remaining_pending = [p for p in q['pending'] if p['id'] not in misclassified_ids]

    # dismissed に追加
    now = _now_iso()
    for entry in misclassified:
        q['dismissed'].append({
            'id': entry['id'],
            'link': entry['link'],
            'kind': entry['kind'],       # old kind（トレーサビリティのため保持）
            'new_kind': new_kind_map[entry['id']],
            'appearances': entry.get('appearances', []),  # リカバリ時の位置情報保持
            'dismissed_at': now,
            'reason': reason,
        })

    q['pending'] = remaining_pending
    save_queue_atomic(queue_path, q)


def _backup_queue(queue_path: Path) -> Path:
    """--apply 前に queue.json を queue.json.bak にコピーする。"""
    import shutil
    backup_path = queue_path.with_suffix('.json.bak')
    shutil.copy2(queue_path, backup_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--queue-path',
        metavar='PATH',
        type=Path,
        default=QUEUE_FILE,
        help=f'queue.json パスをオーバーライド（デフォルト: {QUEUE_FILE}）',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='実際に queue.json を変更する（指定なしは dry-run）。'
             '実行時は queue.json.bak を自動作成する。',
    )
    parser.add_argument(
        '--reason',
        metavar='TEXT',
        default=DEFAULT_REASON,
        help=f'dismiss 理由（デフォルト: "{DEFAULT_REASON}"）',
    )
    parser.add_argument(
        '--pretty',
        action='store_true',
        help='整形出力',
    )
    args = parser.parse_args()

    queue_path: Path = args.queue_path

    try:
        q = load_queue(queue_path)
    except FileNotFoundError as e:
        print(f'error: {e}', file=sys.stderr)
        sys.exit(1)

    pending = q.get('pending', [])
    total_before = len(pending)

    misclassified = detect_misclassified(pending)

    backup_path: Path | None = None
    if args.apply and misclassified:
        backup_path = _backup_queue(queue_path)
        apply_cleanup(queue_path, q, misclassified, args.reason)

    print_summary(
        total_before=total_before,
        misclassified=misclassified,
        apply=args.apply,
        pretty=args.pretty,
    )

    if backup_path is not None:
        print(f'backup: {backup_path} (mv {backup_path} {queue_path} で復元可能)',
              file=sys.stderr)


if __name__ == '__main__':
    main()
