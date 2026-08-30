#!/usr/bin/env python3
"""初始化并维护纯本地的交易日复盘工作流。

示例：
  backend/.venv/bin/python tools/daily_review.py prepare --date 2026-08-05
  backend/.venv/bin/python tools/daily_review.py prompt --date 2026-08-05 --phase premarket
  backend/.venv/bin/python tools/daily_review.py record --date 2026-08-05 --phase close --file close.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from daily_review import PHASES, SOURCE_STATUSES, ReviewWorkflow, ReviewWorkflowError  # noqa: E402


def _item(value: str) -> dict:
    if "=" in value:
        code, name = value.split("=", 1)
    elif ":" in value:
        code, name = value.split(":", 1)
    else:
        code, name = value, value
    return {"code": code.strip(), "name": name.strip()}


def _workflow(args: argparse.Namespace) -> ReviewWorkflow:
    return ReviewWorkflow(args.root) if args.root else ReviewWorkflow()


def _json(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="覆盖本地存储目录（默认 ~/.vibe-research/daily-review）")
    sub = parser.add_subparsers(dest="command", required=True)

    holdings = sub.add_parser("set-holdings", help="替换代码级复盘持仓和清仓排除项")
    holdings.add_argument("--holding", action="append", default=[], metavar="代码=名称")
    holdings.add_argument("--cleared", action="append", default=[], metavar="代码=名称")

    prepare = sub.add_parser("prepare", help="创建指定日期的四阶段复盘档案")
    prepare.add_argument("--date")

    prompt = sub.add_parser("prompt", help="输出指定阶段的固定复盘提示词")
    prompt.add_argument("--date")
    prompt.add_argument("--phase", choices=PHASES, required=True)

    record = sub.add_parser("record", help="把复盘结论写入本地日档")
    record.add_argument("--date")
    record.add_argument("--phase", choices=PHASES, required=True)
    record.add_argument("--file", required=True, help="Markdown 内容文件；使用 - 从 stdin 读取")
    record.add_argument("--data-asof")
    record.add_argument("--source-status", choices=sorted(SOURCE_STATUSES), default="fresh")
    record.add_argument("--source-note", action="append", default=[])

    status = sub.add_parser("status", help="查看基线与当日阶段完成状态")
    status.add_argument("--date")

    args = parser.parse_args()
    workflow = _workflow(args)
    try:
        if args.command == "set-holdings":
            state = workflow.replace_universe(
                [_item(value) for value in args.holding],
                [_item(value) for value in args.cleared],
            )
            _json(
                {
                    "ok": True,
                    "path": str(workflow.state_file),
                    "holdings": len(state["holdings"]),
                    "cleared": len(state["cleared"]),
                }
            )
        elif args.command == "prepare":
            payload, created, path = workflow.prepare_day(args.date)
            _json({"ok": True, "date": payload["date"], "created": created, "path": str(path)})
        elif args.command == "prompt":
            print(workflow.build_prompt(args.phase, args.date))
        elif args.command == "record":
            content = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            payload, path = workflow.record_phase(
                args.phase,
                content,
                args.date,
                data_asof=args.data_asof,
                source_status=args.source_status,
                source_notes=args.source_note,
            )
            _json({"ok": True, "date": payload["date"], "phase": args.phase, "path": str(path)})
        elif args.command == "status":
            _json(workflow.status(args.date))
    except (ReviewWorkflowError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
