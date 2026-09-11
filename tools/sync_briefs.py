#!/usr/bin/env python3
"""Import existing brief task results locally. Never generates briefs or accesses accounts.

Use --data-dir for isolated verification. Default: ${VR_DATA_DIR:-~/.vibe-research}.
Import expects the JSON inside read_thread content[0].text, with thread and turns.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from brief_store import BriefError, SLOTS, configure, day_view, import_thread, record_failure, set_schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir')
    sub = parser.add_subparsers(dest='command', required=True)
    cfg = sub.add_parser('configure')
    cfg.add_argument('--slot', choices=SLOTS, required=True)
    cfg.add_argument('--thread-id', required=True)
    cfg.add_argument('--title', required=True)
    imp = sub.add_parser('import')
    imp.add_argument('--slot', choices=SLOTS, required=True)
    imp.add_argument('--file', required=True, help='JSON file; - reads stdin')
    imp.add_argument('--year-hint', type=int)
    imp.add_argument('--max-output-chars', type=int, default=16000)
    fail = sub.add_parser('failure')
    fail.add_argument('--slot', choices=SLOTS, required=True)
    fail.add_argument('--message', required=True)
    schedule = sub.add_parser('schedule')
    schedule.add_argument('--slot', choices=SLOTS, required=True)
    schedule.add_argument('--automation-id', required=True)
    schedule.add_argument('--times', nargs='+', required=True)
    view = sub.add_parser('status')
    view.add_argument('--date')
    for command in ('start-manual', 'finish-manual'):
        manual = sub.add_parser(command)
        manual.add_argument('--request-id', required=True)
    args = parser.parse_args()
    if args.data_dir:
        os.environ['VR_DATA_DIR'] = args.data_dir
    try:
        if args.command in ('start-manual', 'finish-manual'):
            from brief_manual_sync import start, finish
            result = (start if args.command == 'start-manual' else finish)(args.request_id)
        elif args.command == 'configure':
            result = configure(args.slot, args.thread_id, args.title)
        elif args.command == 'import':
            try:
                raw = sys.stdin.read() if args.file == '-' else Path(args.file).read_text(encoding='utf-8')
                result = import_thread(args.slot, json.loads(raw), args.year_hint, args.max_output_chars)
            except (BriefError, ValueError, OSError) as exc:
                record_failure(args.slot, '同步校验失败：' + str(exc)[:300])
                raise
        elif args.command == 'failure':
            result = record_failure(args.slot, args.message)
        elif args.command == 'schedule':
            result = set_schedule(args.slot, args.automation_id, args.times)
        else:
            result = day_view(args.date)
            for slot in result['slots']:
                if slot['record']:
                    slot['record'].pop('body', None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BriefError, ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
