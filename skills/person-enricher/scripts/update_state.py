#!/usr/bin/env python3
"""
update_state.py: ops/person-enricher/state.json の状態管理。

state.json スキーマ:
  {
    "version": 1,
    "last_run": "ISO8601",
    "last_processed_meeting_date": "YYYY-MM-DD",
    "profile_synthesis": {
      "<人物名>": {
        "last_synthesized_at": "YYYY-MM-DD",
        "observations_since_last": N
      }
    }
  }

アクション:
  --action init [--force]
  --action get
  --action mark-meeting-processed --date YYYY-MM-DD
  --action increment-observation --person <名前>
  --action mark-synthesized --person <名前>
  --action list-pending-synthesis [--threshold-count N] [--threshold-days D]
      観察カウント >= N または前回合成から D 日経過した人物を返す。
      デフォルト: N=3, D=7。

  --action stats
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.vault_io import ENRICHER_DIR, STATE_FILE

JST = timezone(timedelta(hours=9))

DEFAULT_THRESHOLD_COUNT = 3
DEFAULT_THRESHOLD_DAYS = 7


def _now_iso() -> str:
    return datetime.now(JST).isoformat(timespec='seconds')


def _today() -> str:
    return datetime.now(JST).strftime('%Y-%m-%d')


def _empty_state() -> dict:
    return {
        'version': 1,
        'last_run': None,
        'last_processed_meeting_date': '',
        'profile_synthesis': {},
    }


def load_state() -> dict:
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return _empty_state()


def save_state(s: dict) -> None:
    s['last_run'] = _now_iso()
    ENRICHER_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(s, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def cmd_init(force: bool) -> None:
    if STATE_FILE.exists() and not force:
        print(f'state.json already exists. use --force to overwrite.', file=sys.stderr)
        sys.exit(1)
    save_state(_empty_state())
    print(f'initialized: {STATE_FILE}')


def cmd_get() -> dict:
    return load_state()


def cmd_mark_meeting_processed(date: str) -> str:
    s = load_state()
    current = s.get('last_processed_meeting_date') or ''
    if current and current >= date:
        return f'noop: already processed up to {current}'
    s['last_processed_meeting_date'] = date
    save_state(s)
    return f'updated: last_processed_meeting_date {current or "(none)"} -> {date}'


def cmd_increment_observation(person: str) -> dict:
    s = load_state()
    syn = s.setdefault('profile_synthesis', {})
    entry = syn.setdefault(person, {
        'last_synthesized_at': '',
        'observations_since_last': 0,
    })
    entry['observations_since_last'] = int(entry.get('observations_since_last') or 0) + 1
    save_state(s)
    return {
        'person': person,
        'observations_since_last': entry['observations_since_last'],
    }


def cmd_mark_synthesized(person: str) -> str:
    s = load_state()
    syn = s.setdefault('profile_synthesis', {})
    syn[person] = {
        'last_synthesized_at': _today(),
        'observations_since_last': 0,
    }
    save_state(s)
    return f'mark-synthesized: {person} at {_today()}'


def cmd_list_pending_synthesis(threshold_count: int, threshold_days: int) -> list[dict]:
    s = load_state()
    today = datetime.now(JST).date()
    pending = []
    for person, entry in s.get('profile_synthesis', {}).items():
        obs_count = int(entry.get('observations_since_last') or 0)
        last_at = str(entry.get('last_synthesized_at') or '')

        days_since = None
        if last_at:
            try:
                last_date = datetime.strptime(last_at, '%Y-%m-%d').date()
                days_since = (today - last_date).days
            except ValueError:
                days_since = None

        # 条件: count >= threshold_count OR days >= threshold_days
        # ただし1度も合成されていなくて観察数 0 のスキップは noise
        trigger_count = obs_count >= threshold_count
        trigger_days = (days_since is not None and days_since >= threshold_days and obs_count > 0)
        first_synth_with_obs = (not last_at and obs_count >= threshold_count)

        if trigger_count or trigger_days or first_synth_with_obs:
            pending.append({
                'person': person,
                'observations_since_last': obs_count,
                'last_synthesized_at': last_at or None,
                'days_since': days_since,
                'reason': 'count' if trigger_count else ('days' if trigger_days else 'initial'),
            })
    return pending


def cmd_stats() -> dict:
    s = load_state()
    syn = s.get('profile_synthesis', {})
    total = len(syn)
    pending_count = sum(1 for v in syn.values() if int(v.get('observations_since_last') or 0) > 0)
    return {
        'last_run': s.get('last_run'),
        'last_processed_meeting_date': s.get('last_processed_meeting_date'),
        'tracked_persons': total,
        'persons_with_unsynthesized_observations': pending_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', required=True,
                        choices=['init', 'get', 'mark-meeting-processed',
                                 'increment-observation', 'mark-synthesized',
                                 'list-pending-synthesis', 'stats'])
    parser.add_argument('--date', help='YYYY-MM-DD')
    parser.add_argument('--person', help='人物名')
    parser.add_argument('--threshold-count', type=int, default=DEFAULT_THRESHOLD_COUNT)
    parser.add_argument('--threshold-days', type=int, default=DEFAULT_THRESHOLD_DAYS)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args()

    pretty = 2 if args.pretty else None

    if args.action == 'init':
        cmd_init(args.force)
        return

    if args.action == 'get':
        print(json.dumps(cmd_get(), ensure_ascii=False, indent=pretty))
        return

    if args.action == 'mark-meeting-processed':
        if not args.date:
            print('error: --date required', file=sys.stderr); sys.exit(1)
        print(cmd_mark_meeting_processed(args.date))
        return

    if args.action == 'increment-observation':
        if not args.person:
            print('error: --person required', file=sys.stderr); sys.exit(1)
        print(json.dumps(cmd_increment_observation(args.person), ensure_ascii=False, indent=pretty))
        return

    if args.action == 'mark-synthesized':
        if not args.person:
            print('error: --person required', file=sys.stderr); sys.exit(1)
        print(cmd_mark_synthesized(args.person))
        return

    if args.action == 'list-pending-synthesis':
        items = cmd_list_pending_synthesis(args.threshold_count, args.threshold_days)
        print(json.dumps(items, ensure_ascii=False, indent=pretty))
        return

    if args.action == 'stats':
        print(json.dumps(cmd_stats(), ensure_ascii=False, indent=pretty))
        return


if __name__ == '__main__':
    main()
