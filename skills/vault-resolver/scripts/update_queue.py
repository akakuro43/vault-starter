#!/usr/bin/env python3
"""
update_queue.py: ops/resolver/queue.json の状態管理。

queue スキーマ:
  {
    "version": 1,
    "updated_at": "ISO8601",
    "pending":   [{ id, link, kind, appearances, candidates, first_seen, notified_at }, ...],
    "resolved":  [{ id, link, kind, resolved_at, action, target }, ...],
    "dismissed": [{ id, link, kind, dismissed_at, reason }, ...]
  }

アクション:
  --action add-pending --items-json <JSON>
      新規 pending を追加。重複（同じ link）は appearances を統合。
      resolved / dismissed 済みの link は無視。
      標準入力からも読める: --items-json -

  --action list-pending [--unnotified]
      pending を JSON で出力。--unnotified は notified_at が null のもののみ。

  --action mark-notified --ids <id,id,...>
      指定 id の notified_at を今日の日付に。

  --action resolve --id <id> --target <name> [--method create|alias]
      pending → resolved。

  --action dismiss --id <id> [--reason <text>]
      pending → dismissed。

  --action init
      queue.json を空で初期化（既存があれば上書き拒否、--force で上書き）。

  --action stats
      件数サマリを出力。
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import QUEUE_FILE, RESOLVER_DIR

JST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(JST).isoformat(timespec='seconds')


def _today() -> str:
    return datetime.now(JST).strftime('%Y-%m-%d')


def _new_id() -> str:
    return f'p_{secrets.token_hex(3)}'


def _empty_queue() -> dict:
    return {
        'version': 1,
        'updated_at': None,
        'pending': [],
        'resolved': [],
        'dismissed': [],
    }


def load_queue() -> dict:
    if not QUEUE_FILE.exists():
        return _empty_queue()
    try:
        return json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return _empty_queue()


def save_queue(q: dict) -> None:
    q['updated_at'] = _now_iso()
    RESOLVER_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(
        json.dumps(q, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


# ── アクション実装 ────────────────────────────────────
def cmd_init(force: bool) -> None:
    if QUEUE_FILE.exists() and not force:
        print(f'queue.json already exists. use --force to overwrite.', file=sys.stderr)
        sys.exit(1)
    save_queue(_empty_queue())
    print(f'initialized: {QUEUE_FILE}')


def cmd_add_pending(items: list[dict]) -> dict:
    q = load_queue()
    pending_links = {p['link']: p for p in q['pending']}
    resolved_links = {r.get('link') for r in q.get('resolved', [])}
    dismissed_links = {d.get('link') for d in q.get('dismissed', [])}

    added = 0
    updated = 0
    skipped = 0

    for item in items:
        link = item.get('link')
        if not link:
            continue
        if link in resolved_links or link in dismissed_links:
            skipped += 1
            continue

        if link in pending_links:
            # appearances 統合
            ex = pending_links[link]
            ex_keys = {(a.get('file'), a.get('line')) for a in ex.get('appearances', [])}
            new_apps = [
                a for a in item.get('appearances', [])
                if (a.get('file'), a.get('line')) not in ex_keys
            ]
            if new_apps:
                ex.setdefault('appearances', []).extend(new_apps)
                updated += 1
            # candidates は新しい結果で更新
            if 'candidates' in item:
                ex['candidates'] = item['candidates']
        else:
            entry = {
                'id': _new_id(),
                'link': link,
                'kind': item.get('kind', 'unknown'),
                'appearances': item.get('appearances', []),
                'candidates': item.get('candidates', []),
                'first_seen': _today(),
                'notified_at': None,
            }
            q['pending'].append(entry)
            pending_links[link] = entry
            added += 1

    save_queue(q)
    return {'added': added, 'updated': updated, 'skipped': skipped, 'total_pending': len(q['pending'])}


def cmd_list_pending(unnotified_only: bool) -> list[dict]:
    q = load_queue()
    items = q.get('pending', [])
    if unnotified_only:
        items = [p for p in items if not p.get('notified_at')]
    return items


def cmd_mark_notified(ids: list[str]) -> dict:
    q = load_queue()
    today = _today()
    matched = 0
    id_set = set(ids)
    for p in q.get('pending', []):
        if p.get('id') in id_set:
            p['notified_at'] = today
            matched += 1
    save_queue(q)
    return {'matched': matched, 'requested': len(ids)}


def cmd_resolve(target_id: str, target_name: str, method: str) -> str:
    q = load_queue()
    for i, p in enumerate(q.get('pending', [])):
        if p.get('id') == target_id:
            entry = q['pending'].pop(i)
            q['resolved'].append({
                'id': entry['id'],
                'link': entry['link'],
                'kind': entry.get('kind'),
                'resolved_at': _now_iso(),
                'action': method,
                'target': target_name,
            })
            save_queue(q)
            return f'resolved: {entry["link"]} -> {target_name} ({method})'
    raise ValueError(f'pending id not found: {target_id}')


def cmd_dismiss(target_id: str, reason: str) -> str:
    q = load_queue()
    for i, p in enumerate(q.get('pending', [])):
        if p.get('id') == target_id:
            entry = q['pending'].pop(i)
            q['dismissed'].append({
                'id': entry['id'],
                'link': entry['link'],
                'kind': entry.get('kind'),
                'dismissed_at': _now_iso(),
                'reason': reason,
            })
            save_queue(q)
            return f'dismissed: {entry["link"]} (reason: {reason})'
    raise ValueError(f'pending id not found: {target_id}')


def cmd_stats() -> dict:
    q = load_queue()
    return {
        'pending': len(q.get('pending', [])),
        'pending_unnotified': sum(1 for p in q.get('pending', []) if not p.get('notified_at')),
        'resolved': len(q.get('resolved', [])),
        'dismissed': len(q.get('dismissed', [])),
        'updated_at': q.get('updated_at'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', required=True,
                        choices=['init', 'add-pending', 'list-pending', 'mark-notified',
                                 'resolve', 'dismiss', 'stats'])
    parser.add_argument('--items-json', help='JSON 文字列または "-" で標準入力')
    parser.add_argument('--unnotified', action='store_true')
    parser.add_argument('--ids', help='カンマ区切りの id リスト')
    parser.add_argument('--id', help='単一 id')
    parser.add_argument('--target', help='resolve 先の名前')
    parser.add_argument('--method', default='create', choices=['create', 'alias'])
    parser.add_argument('--reason', default='')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args()

    if args.action == 'init':
        cmd_init(args.force)
        return

    if args.action == 'add-pending':
        if not args.items_json:
            print('error: --items-json required', file=sys.stderr)
            sys.exit(1)
        raw = sys.stdin.read() if args.items_json == '-' else args.items_json
        items = json.loads(raw)
        result = cmd_add_pending(items)
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return

    if args.action == 'list-pending':
        items = cmd_list_pending(args.unnotified)
        print(json.dumps(items, ensure_ascii=False, indent=2 if args.pretty else None))
        return

    if args.action == 'mark-notified':
        if not args.ids:
            print('error: --ids required', file=sys.stderr)
            sys.exit(1)
        result = cmd_mark_notified([s.strip() for s in args.ids.split(',') if s.strip()])
        print(json.dumps(result, ensure_ascii=False))
        return

    if args.action == 'resolve':
        if not args.id or not args.target:
            print('error: --id and --target required', file=sys.stderr)
            sys.exit(1)
        try:
            print(cmd_resolve(args.id, args.target, args.method))
        except ValueError as e:
            print(f'error: {e}', file=sys.stderr)
            sys.exit(1)
        return

    if args.action == 'dismiss':
        if not args.id:
            print('error: --id required', file=sys.stderr)
            sys.exit(1)
        try:
            print(cmd_dismiss(args.id, args.reason))
        except ValueError as e:
            print(f'error: {e}', file=sys.stderr)
            sys.exit(1)
        return

    if args.action == 'stats':
        result = cmd_stats()
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return


if __name__ == '__main__':
    main()
