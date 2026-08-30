"""交易日复盘工作流的纯本地状态与归档层。

仓库只保存规则；私人持仓代码和每日结论默认写到
``~/.vibe-research/daily-review``。本模块不联网、不执行交易，也不保存数量和成本。
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


BEIJING = timezone(timedelta(hours=8))
SCHEMA_VERSION = 1
SOURCE_STATUSES = {"not_checked", "fresh", "partial", "stale", "failed"}

PHASES = {
    "premarket": {
        "title": "盘前复盘",
        "trigger": "盘前复盘",
        "suggested_time": "08:30-08:50",
        "checks": [
            "隔夜美股、QQQ、SOXX/SMH及核心科技股强弱",
            "韩国市场、美元/人民币、美国长债、黄金与原油",
            "交易所公告、政策与突发消息；区分事实、观点和情绪",
            "外盘与当前持仓、行业板块的映射",
            "强势、中性、弱势三套开盘预案",
        ],
    },
    "auction": {
        "title": "竞价复盘",
        "trigger": "竞价复盘",
        "suggested_time": "09:26",
        "checks": [
            "上证50/沪深300与中证1000/双创的竞价相对强弱",
            "持仓和主要板块的高低开幅度、竞价量与异常封单",
            "高开是否透支隔夜利好，是否满足追涨或反T条件",
            "给出9:30-10:00确认条件和失效条件",
        ],
    },
    "midday": {
        "title": "午盘复盘",
        "trigger": "午盘复盘",
        "suggested_time": "11:35",
        "checks": [
            "主要指数、半日成交额及相对上一交易日同期变化",
            "涨跌家数、涨跌停、市场宽度和权重/小盘相对强弱",
            "领涨、回落和逆势板块的量价变化",
            "持仓相对行业、指数及分时均价线的强弱",
            "下午持有、正T、反T或停止交易的条件",
        ],
    },
    "close": {
        "title": "盘后复盘",
        "trigger": "盘后复盘",
        "suggested_time": "15:10",
        "checks": [
            "主要指数日K、成交额、市场宽度与尾盘变化",
            "行业和概念的领涨、分歧、轮动及量价确认",
            "持仓收盘表现及相对板块强弱，不推测未知账户收益",
            "当日预案核对：哪些成立、哪些失效、误差来自哪里",
            "次日关键价位、量能确认、正T/反T与不交易条件",
        ],
    },
}

DEFAULT_POLICY = {
    "research_horizon": "short_term",
    "rolling_windows": [20, 40],
    "external_market_role": "volatility_and_opening_filter",
    "required_market_context": [
        "上证指数",
        "沪深300",
        "中证1000",
        "创业板指",
        "科创50",
    ],
    "source_priority": ["交易所及公司公告", "权威快讯", "公开行情", "行业媒体", "社交情绪"],
    "privacy": "查询私人持仓行情前需明确授权；只发送代码，不发送数量和成本",
    "data_discipline": "所有实时结论标注数据日期和截至时间；失败或旧缓存必须显式标记",
}


class ReviewWorkflowError(ValueError):
    """复盘工作流输入或状态不合法。"""


def _now() -> str:
    return datetime.now(BEIJING).isoformat(timespec="minutes")


def _validate_date(value: str | None) -> str:
    if not value:
        return datetime.now(BEIJING).date().isoformat()
    try:
        return date_type.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ReviewWorkflowError("日期格式应为 YYYY-MM-DD") from exc


def _normalize_items(items: Iterable[dict] | None) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for raw in items or []:
        code = str(raw.get("code") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not (len(code) == 6 and code.isdigit()):
            raise ReviewWorkflowError(f"无效证券代码：{code or '<empty>'}")
        if code in seen:
            continue
        seen.add(code)
        result.append({"code": code, "name": name or code})
    return result


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class ReviewWorkflow:
    """管理代码级基线与每日四阶段复盘档案。"""

    def __init__(self, root: str | Path | None = None):
        if root is None:
            data_dir = Path(os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research")
            root = data_dir / "daily-review"
        self.root = Path(root).expanduser()
        self.state_file = self.root / "state.json"
        self.days_dir = self.root / "days"

    def get_state(self) -> dict:
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            payload = {}
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": payload.get("updated_at"),
            "holdings": _normalize_items(payload.get("holdings")),
            "cleared": _normalize_items(payload.get("cleared")),
            "policy": deepcopy(payload.get("policy") or DEFAULT_POLICY),
        }

    def replace_universe(self, holdings: Iterable[dict], cleared: Iterable[dict] | None = None) -> dict:
        current = _normalize_items(holdings)
        current_codes = {item["code"] for item in current}
        exited = [item for item in _normalize_items(cleared) if item["code"] not in current_codes]
        state = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": _now(),
            "holdings": current,
            "cleared": exited,
            "policy": deepcopy(DEFAULT_POLICY),
        }
        _atomic_json(self.state_file, state)
        return state

    def _day_paths(self, review_date: str) -> tuple[Path, Path]:
        return self.days_dir / f"{review_date}.json", self.days_dir / f"{review_date}.md"

    def _new_day(self, review_date: str) -> dict:
        state = self.get_state()
        timestamp = _now()
        return {
            "schema_version": SCHEMA_VERSION,
            "date": review_date,
            "created_at": timestamp,
            "updated_at": timestamp,
            "state_updated_at": state.get("updated_at"),
            "holdings_snapshot": deepcopy(state["holdings"]),
            "cleared_snapshot": deepcopy(state["cleared"]),
            "trades": [],
            "policy": deepcopy(state["policy"]),
            "phases": {
                key: {
                    "title": meta["title"],
                    "status": "pending",
                    "data_asof": None,
                    "source_status": "not_checked",
                    "source_notes": [],
                    "content": "",
                }
                for key, meta in PHASES.items()
            },
        }

    def prepare_day(self, review_date: str | None = None) -> tuple[dict, bool, Path]:
        day = _validate_date(review_date)
        json_path, md_path = self._day_paths(day)
        created = False
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            payload = self._new_day(day)
            _atomic_json(json_path, payload)
            created = True
        _atomic_text(md_path, self.render_markdown(payload))
        return payload, created, md_path

    def load_day(self, review_date: str | None = None) -> dict:
        day = _validate_date(review_date)
        json_path, _ = self._day_paths(day)
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ReviewWorkflowError(f"{day} 尚未创建复盘档案，请先运行 prepare") from exc

    def build_prompt(self, phase: str, review_date: str | None = None) -> str:
        if phase not in PHASES:
            raise ReviewWorkflowError(f"未知复盘阶段：{phase}")
        payload, _, _ = self.prepare_day(review_date)
        meta = PHASES[phase]
        holding_lines = [f"- {item['code']} {item['name']}" for item in payload["holdings_snapshot"]]
        cleared_lines = [f"- {item['code']} {item['name']}" for item in payload["cleared_snapshot"]]
        trade_lines = [
            (
                f"- {item.get('reported_at') or item.get('date')} {item.get('side', '').upper()} "
                f"{item['code']} {item.get('name', '')} {item.get('quantity')}股 @{item.get('price')}"
            )
            for item in payload.get("trades") or []
        ]
        checks = [f"{index}. {item}" for index, item in enumerate(meta["checks"], 1)]
        return "\n".join(
            [
                f"请完成 {payload['date']} {meta['title']}。",
                "",
                "数据纪律：",
                f"- {payload['policy']['data_discipline']}",
                "- 旧缓存、失败源和盘中未收盘数据必须明确标记，不得冒充最终数据。",
                "- 外盘只作波动与开盘过滤器，不直接预测A股收盘方向。",
                "- 查询以下私人持仓行情前，先说明只发送代码、不发送数量和成本，并等待明确同意。",
                "",
                "当前复盘持仓：",
                *(holding_lines or ["- （尚未设置）"]),
                "",
                "已清仓、不得计入当前组合：",
                *(cleared_lines or ["- （无）"]),
                "",
                "当日已记录交易（数量和成本只用于本地复盘，不得发送给行情源）：",
                *(trade_lines or ["- （无）"]),
                "",
                "固定检查项：",
                *checks,
                "",
                "固定输出：一句话定性；指数与市场宽度；板块量价；持仓相对强弱；",
                "正T/反T/不交易条件；关键价格、确认条件、失效条件；数据截至时间与来源状态。",
            ]
        )

    def record_phase(
        self,
        phase: str,
        content: str,
        review_date: str | None = None,
        *,
        data_asof: str | None = None,
        source_status: str = "fresh",
        source_notes: Iterable[str] | None = None,
    ) -> tuple[dict, Path]:
        if phase not in PHASES:
            raise ReviewWorkflowError(f"未知复盘阶段：{phase}")
        if source_status not in SOURCE_STATUSES:
            raise ReviewWorkflowError(f"未知数据源状态：{source_status}")
        if not content.strip():
            raise ReviewWorkflowError("复盘内容不能为空")
        payload, _, _ = self.prepare_day(review_date)
        payload["phases"][phase].update(
            {
                "status": "completed",
                "data_asof": data_asof or _now(),
                "source_status": source_status,
                "source_notes": [str(note).strip() for note in source_notes or [] if str(note).strip()],
                "content": content.strip(),
            }
        )
        payload["updated_at"] = _now()
        json_path, md_path = self._day_paths(payload["date"])
        _atomic_json(json_path, payload)
        _atomic_text(md_path, self.render_markdown(payload))
        return payload, md_path

    @staticmethod
    def render_markdown(payload: dict) -> str:
        holdings = payload.get("holdings_snapshot") or []
        cleared = payload.get("cleared_snapshot") or []
        trades = payload.get("trades") or []
        lines = [
            "---",
            f"date: {payload['date']}",
            f"schema_version: {payload.get('schema_version', SCHEMA_VERSION)}",
            f"state_updated_at: {payload.get('state_updated_at') or 'null'}",
            "---",
            "",
            f"# {payload['date']} 交易日复盘",
            "",
            "> 本文件为本地私人复盘档案。实时结论必须标注数据截至时间；失败或旧缓存不得当作最新数据。",
            "",
            "## 当日持仓快照",
            "",
            "| 代码 | 名称 |",
            "|---|---|",
        ]
        lines.extend([f"| {item['code']} | {item['name']} |" for item in holdings] or ["| — | 尚未设置 |"])
        lines.extend(["", "## 已清仓排除项", ""])
        lines.extend([f"- {item['code']} {item['name']}" for item in cleared] or ["- 无"])
        lines.extend(["", "## 当日交易", ""])
        if trades:
            lines.extend(
                [
                    "| 时间 | 方向 | 代码 | 名称 | 数量 | 成交价 | 名义金额 | 交易ID |",
                    "|---|---|---|---|---:|---:|---:|---|",
                ]
            )
            for item in trades:
                side = {"buy": "买入", "sell": "卖出"}.get(item.get("side"), item.get("side", "—"))
                lines.append(
                    f"| {item.get('reported_at') or item.get('date') or '—'} | {side} | "
                    f"{item.get('code', '—')} | {item.get('name', '—')} | "
                    f"{item.get('quantity', '—')} | {item.get('price', '—')} | "
                    f"{item.get('amount', '—')} | `{item.get('id', '—')}` |"
                )
        else:
            lines.append("- 无")

        for key, meta in PHASES.items():
            phase = payload["phases"][key]
            lines.extend(
                [
                    "",
                    f"## {meta['title']}（建议 {meta['suggested_time']}）",
                    "",
                    f"- 状态：`{phase['status']}`",
                    f"- 数据截至：{phase.get('data_asof') or '待填写'}",
                    f"- 数据源状态：`{phase.get('source_status') or 'not_checked'}`",
                ]
            )
            for note in phase.get("source_notes") or []:
                lines.append(f"- 数据说明：{note}")
            lines.extend(["", "### 检查清单", ""])
            lines.extend([f"- [ ] {item}" for item in meta["checks"]])
            lines.extend(["", "### 复盘结论", "", phase.get("content") or "> 待生成"])
        return "\n".join(lines).rstrip() + "\n"

    def status(self, review_date: str | None = None) -> dict:
        state = self.get_state()
        result = {
            "root": str(self.root),
            "state_updated_at": state.get("updated_at"),
            "holdings": len(state["holdings"]),
            "cleared": len(state["cleared"]),
        }
        if review_date:
            payload = self.load_day(review_date)
            result["date"] = payload["date"]
            result["trades"] = len(payload.get("trades") or [])
            result["phases"] = {key: value["status"] for key, value in payload["phases"].items()}
        return result
