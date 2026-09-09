"""本地交易记账事务：一次同步持仓、复盘基线、当日快照和私有台账。

本模块不联网，也不调用行情接口。所有目标文件先写到同目录临时文件，
再统一替换；任一步替换失败会恢复已经替换的文件。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterator

try:  # macOS/Linux；Windows 环境降级为进程内无锁
    import fcntl
except ImportError:  # pragma: no cover - 当前项目运行于 macOS/Linux
    fcntl = None

from daily_review import (
    BEIJING,
    DEFAULT_POLICY,
    SCHEMA_VERSION,
    ReviewWorkflow,
    _normalize_items,
    _validate_date,
)


TRADE_SCHEMA_VERSION = 1


class TradeError(ValueError):
    """交易记账输入或本地状态不合法。"""


def _json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TradeError(f"本地文件损坏或不可读：{path}") from exc
    if not isinstance(value, dict):
        raise TradeError(f"本地文件格式错误：{path}")
    return value


def _decimal(value: str | int | float, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TradeError(f"{field}不是有效数字") from exc
    if not result.is_finite() or result <= 0:
        raise TradeError(f"{field}必须大于0")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _cost(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _number(value: Decimal, *, places: int = 4) -> str:
    rendered = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _currency(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"¥{int(value):,}"
    return f"¥{value:,.2f}"


def _quantity(value: int | float) -> str:
    numeric = float(value)
    return f"{int(numeric):,}" if numeric.is_integer() else f"{numeric:,.4f}".rstrip("0").rstrip(".")


def _now_iso() -> str:
    return datetime.now(BEIJING).isoformat(timespec="minutes")


def _default_ledger() -> str:
    return """# 交易台账（私有，不进仓库）

> 本文件记录用户主动报备的交易和决策上下文。

## 当前持仓

| 开仓日 | 标的 | 方向 | 数量 | 均价 | 成本额 | 关联研究 |
|---|---|---|---|---|---|---|

## 决策记录

## 平仓记录

（无）
"""


def _table_row(
    *,
    open_date: str,
    code: str,
    name: str,
    shares: int | float,
    average_cost: Decimal,
    research: str,
) -> str:
    total = _money(Decimal(str(shares)) * average_cost)
    return (
        f"| {open_date} | {code} {name} | 买入 | {_quantity(shares)} | "
        f"{_number(average_cost)} | {_currency(total)} | {research} |"
    )


def _update_ledger(content: str, trade: dict, position: dict) -> str:
    text = content if content.strip() else _default_ledger()
    marker = f"<!-- trade-id:{trade['id']} -->"
    if marker in text:
        return text if text.endswith("\n") else text + "\n"

    lines = text.splitlines()
    try:
        holdings_heading = lines.index("## 当前持仓")
    except ValueError:
        lines.extend(
            [
                "",
                "## 当前持仓",
                "",
                "| 开仓日 | 标的 | 方向 | 数量 | 均价 | 成本额 | 关联研究 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        holdings_heading = lines.index("## 当前持仓")

    next_heading = next(
        (index for index in range(holdings_heading + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    code_prefix = f"{trade['code']} "
    existing_index = None
    existing_date = trade["date"]
    existing_research = "自动交易记录"
    table_rows: list[int] = []
    for index in range(holdings_heading + 1, next_heading):
        line = lines[index]
        if not line.startswith("|"):
            continue
        table_rows.append(index)
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 7 and cells[1].startswith(code_prefix):
            existing_index = index
            existing_date = cells[0] or trade["date"]
            existing_research = cells[6] or "自动交易记录"
            break

    row = _table_row(
        open_date=existing_date,
        code=trade["code"],
        name=trade["name"],
        shares=position["shares"],
        average_cost=Decimal(str(position["cost"])),
        research=existing_research,
    )
    if existing_index is not None:
        lines[existing_index] = row
    else:
        insert_at = (max(table_rows) + 1) if table_rows else holdings_heading + 1
        lines.insert(insert_at, row)

    try:
        decision_heading = lines.index("## 决策记录")
    except ValueError:
        lines.extend(["", "## 决策记录", ""])
        decision_heading = lines.index("## 决策记录")

    entry = [
        "",
        marker,
        f"### {trade['date']} 买入 {trade['code']} @{_number(Decimal(str(trade['price'])))}",
        (
            f"- **成交记录**：买入{trade['name']} {_quantity(trade['quantity'])}股，"
            f"成交价{_number(Decimal(str(trade['price'])))}元；名义成交额"
            f"{_currency(Decimal(str(trade['amount'])))}，未计佣金等费用。"
        ),
        f"- **记录时间**：{trade['reported_at']}；交易ID `{trade['id']}`。",
        "- **决策上下文**：买入理由、计划周期和退出条件未提供时保持待补，不自动推测。",
    ]
    lines[decision_heading + 1 : decision_heading + 1] = entry
    return "\n".join(lines).rstrip() + "\n"


def _update_sell_ledger(content: str, trade: dict, position: dict | None) -> str:
    text = content if content.strip() else _default_ledger()
    marker = f"<!-- trade-id:{trade['id']} -->"
    if marker in text:
        return text if text.endswith("\n") else text + "\n"

    lines = text.splitlines()
    if "## 当前持仓" in lines:
        heading = lines.index("## 当前持仓")
        next_heading = next(
            (index for index in range(heading + 1, len(lines)) if lines[index].startswith("## ")),
            len(lines),
        )
        for index in range(heading + 1, next_heading):
            line = lines[index]
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 7 or not cells[1].startswith(f"{trade['code']} "):
                continue
            if position and float(position.get("shares", 0)) > 0:
                lines[index] = _table_row(
                    open_date=cells[0] or trade["date"],
                    code=trade["code"],
                    name=trade["name"],
                    shares=position["shares"],
                    average_cost=Decimal(str(position["cost"])),
                    research=cells[6] or "自动交易记录",
                )
            else:
                lines.pop(index)
            break

    try:
        decision_heading = lines.index("## 决策记录")
    except ValueError:
        lines.extend(["", "## 决策记录", ""])
        decision_heading = lines.index("## 决策记录")
    action = "清仓卖出" if trade.get("close_position") else "部分卖出"
    entry = [
        "",
        marker,
        f"### {trade['date']} {action} {trade['code']} @{_number(Decimal(str(trade['price'])))}",
        (
            f"- **成交记录**：卖出{trade['name']} {_quantity(trade['quantity'])}股，"
            f"成交价{_number(Decimal(str(trade['price'])))}元，成本"
            f"{_number(Decimal(str(trade['cost'])))}元。"
        ),
        (
            f"- **毛收益**：{_currency(Decimal(str(trade['pnl'])))}，"
            f"收益率{trade['pnl_pct']:.2f}%；未计佣金、印花税等费用。"
        ),
        f"- **记录时间**：{trade['reported_at']}；交易ID `{trade['id']}`。",
    ]
    lines[decision_heading + 1 : decision_heading + 1] = entry
    return "\n".join(lines).rstrip() + "\n"


def _write_temp(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.trade-", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(temp_path, path.stat().st_mode & 0o777)
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _atomic_batch(
    updates: dict[Path, bytes],
    *,
    replace: Callable[[str | bytes | os.PathLike, str | bytes | os.PathLike], None] = os.replace,
) -> None:
    originals = {path: path.read_bytes() if path.exists() else None for path in updates}
    staged: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for path, content in updates.items():
            staged[path] = _write_temp(path, content)
        for path, temp_path in staged.items():
            replace(temp_path, path)
            committed.append(path)
    except Exception:
        for path in reversed(committed):
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                restore = _write_temp(path, original)
                replace(restore, path)
        raise
    finally:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class TradeService:
    """执行无网络、可幂等、带回滚的本地交易记账。"""

    def __init__(
        self,
        data_dir: str | Path | None = None,
        ledger_path: str | Path | None = None,
        *,
        replace: Callable[[str | bytes | os.PathLike, str | bytes | os.PathLike], None] = os.replace,
    ):
        self.data_dir = Path(
            data_dir or os.environ.get("VR_DATA_DIR") or Path.home() / ".vibe-research"
        ).expanduser()
        self.portfolio_path = self.data_dir / "portfolio.json"
        self.trades_path = self.data_dir / "trades.json"
        self.lock_path = self.data_dir / "trade.lock"
        self.workflow = ReviewWorkflow(self.data_dir / "daily-review")
        repo_root = Path(__file__).resolve().parents[1]
        self.ledger_path = Path(ledger_path or repo_root / "research" / "交易台账.md").expanduser()
        self._replace = replace

    def buy(
        self,
        code: str,
        *,
        quantity: int,
        price: str | int | float,
        name: str | None = None,
        trade_date: str | None = None,
        reported_at: str | None = None,
        trade_id: str | None = None,
        dry_run: bool = False,
        chronological: bool = False,
    ) -> dict:
        started = time.perf_counter()
        code = str(code).strip()
        if len(code) != 6 or not code.isdigit():
            raise TradeError("证券代码必须是6位数字")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise TradeError("数量必须是正整数")
        price_value = _decimal(price, "价格")
        day = _validate_date(trade_date)
        timestamp = str(reported_at or _now_iso()).strip()
        identity = str(trade_id or uuid.uuid4().hex).strip()
        if not identity:
            raise TradeError("交易ID不能为空")

        with _lock(self.lock_path):
            trade_log = _read_json(
                self.trades_path,
                {"schema_version": TRADE_SCHEMA_VERSION, "trades": []},
            )
            trades = trade_log.setdefault("trades", [])
            duplicate = next((item for item in trades if item.get("id") == identity), None)
            if duplicate is not None:
                expected = (code, quantity, float(price_value), day, "buy")
                actual = (
                    duplicate.get("code"),
                    duplicate.get("quantity"),
                    float(duplicate.get("price", 0)),
                    duplicate.get("date"),
                    duplicate.get("side"),
                )
                if actual != expected:
                    raise TradeError(f"交易ID冲突：{identity} 已用于另一笔交易")
                return {
                    "ok": True,
                    "action": "buy",
                    "trade_id": identity,
                    "already_recorded": True,
                    "dry_run": False,
                    "position": duplicate.get("position_after"),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }

            if chronological and any(t.get("code") == code and t.get("date", "") > day for t in trades):
                raise TradeError("请按成交日期顺序补录，不能将更早成交直接应用到当前持仓")
            portfolio = _read_json(self.portfolio_path, {"holdings": [], "last_refresh": None})
            portfolio.setdefault("holdings", [])
            state_raw = _read_json(self.workflow.state_file, {})
            state = {
                "schema_version": SCHEMA_VERSION,
                "updated_at": state_raw.get("updated_at"),
                "holdings": _normalize_items(state_raw.get("holdings")),
                "cleared": _normalize_items(state_raw.get("cleared")),
                "policy": state_raw.get("policy") or DEFAULT_POLICY,
            }
            resolved_name = str(name or "").strip()
            if not resolved_name:
                resolved_name = next(
                    (item["name"] for item in state["holdings"] if item["code"] == code),
                    code,
                )

            existing = next((item for item in portfolio["holdings"] if item.get("code") == code), None)
            old_shares = Decimal(str(existing.get("shares", 0))) if existing else Decimal("0")
            old_cost = Decimal(str(existing.get("cost", 0))) if existing else Decimal("0")
            new_shares = old_shares + Decimal(quantity)
            average = _cost((old_shares * old_cost + Decimal(quantity) * price_value) / new_shares)
            position = {
                "code": code,
                "name": resolved_name,
                "shares": int(new_shares) if new_shares == new_shares.to_integral_value() else float(new_shares),
                "cost": float(average),
            }
            if existing is None:
                portfolio["holdings"].append({key: position[key] for key in ("code", "shares", "cost")})
            else:
                existing.update({"shares": position["shares"], "cost": position["cost"]})

            holding_map = {item["code"]: item for item in state["holdings"]}
            if code in holding_map:
                holding_map[code]["name"] = resolved_name
            else:
                state["holdings"].append({"code": code, "name": resolved_name})
            state["cleared"] = [item for item in state["cleared"] if item["code"] != code]
            state["updated_at"] = _now_iso()

            day_json, day_markdown = self.workflow._day_paths(day)
            if day_json.exists():
                day_payload = _read_json(day_json, {})
            else:
                day_payload = self.workflow._new_day(day)
            day_payload["holdings_snapshot"] = list(state["holdings"])
            day_payload["cleared_snapshot"] = list(state["cleared"])
            day_payload["state_updated_at"] = state["updated_at"]
            day_payload["updated_at"] = _now_iso()

            amount = _money(Decimal(quantity) * price_value)
            trade = {
                "id": identity,
                "side": "buy",
                "date": day,
                "reported_at": timestamp,
                "code": code,
                "name": resolved_name,
                "quantity": quantity,
                "price": float(price_value),
                "amount": float(amount),
                "position_after": position,
            }
            day_payload.setdefault("trades", []).append(trade)
            trades.append(trade)
            trade_log["schema_version"] = TRADE_SCHEMA_VERSION

            ledger = self.ledger_path.read_text(encoding="utf-8") if self.ledger_path.exists() else _default_ledger()
            updated_ledger = _update_ledger(ledger, trade, position)
            updates = {
                self.portfolio_path: _json_text(portfolio).encode("utf-8"),
                self.workflow.state_file: _json_text(state).encode("utf-8"),
                day_json: _json_text(day_payload).encode("utf-8"),
                day_markdown: self.workflow.render_markdown(day_payload).encode("utf-8"),
                self.ledger_path: updated_ledger.encode("utf-8"),
                self.trades_path: _json_text(trade_log).encode("utf-8"),
            }
            if not dry_run:
                try:
                    _atomic_batch(updates, replace=self._replace)
                except OSError as exc:
                    raise TradeError(f"交易记账失败，已回滚：{exc}") from exc

        return {
            "ok": True,
            "action": "buy",
            "trade_id": identity,
            "already_recorded": False,
            "dry_run": dry_run,
            "trade": {key: trade[key] for key in ("date", "code", "name", "quantity", "price", "amount")},
            "position": position,
            "holding_count": len(state["holdings"]),
            "paths": {
                "portfolio": str(self.portfolio_path),
                "review_state": str(self.workflow.state_file),
                "day": str(day_markdown),
                "ledger": str(self.ledger_path),
                "trades": str(self.trades_path),
            },
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def sell(
        self,
        code: str,
        *,
        quantity: int,
        price: str | int | float,
        cost: str | int | float | None,
        name: str | None = None,
        trade_date: str | None = None,
        reported_at: str | None = None,
        trade_id: str | None = None,
        close_position: bool = False,
        dry_run: bool = False,
        chronological: bool = False,
    ) -> dict:
        started = time.perf_counter()
        code = str(code).strip()
        if len(code) != 6 or not code.isdigit():
            raise TradeError("证券代码必须是6位数字")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise TradeError("数量必须是正整数")
        price_value = _decimal(price, "价格")
        cost_value = _decimal(cost, "成本") if cost is not None else None
        day = _validate_date(trade_date)
        timestamp = str(reported_at or _now_iso()).strip()
        identity = str(trade_id or uuid.uuid4().hex).strip()

        with _lock(self.lock_path):
            trade_log = _read_json(
                self.trades_path,
                {"schema_version": TRADE_SCHEMA_VERSION, "trades": []},
            )
            trades = trade_log.setdefault("trades", [])
            duplicate = next((item for item in trades if item.get("id") == identity), None)
            if duplicate is not None:
                expected = (code, quantity, float(price_value), float(cost_value) if cost_value is not None else float(duplicate.get("cost", 0)), day, "sell")
                actual = (
                    duplicate.get("code"),
                    duplicate.get("quantity"),
                    float(duplicate.get("price", 0)),
                    float(duplicate.get("cost", 0)),
                    duplicate.get("date"),
                    duplicate.get("side"),
                )
                if actual != expected:
                    raise TradeError(f"交易ID冲突：{identity} 已用于另一笔交易")
                return {
                    "ok": True,
                    "action": "sell",
                    "trade_id": identity,
                    "already_recorded": True,
                    "dry_run": False,
                    "pnl": duplicate.get("pnl"),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }

            if chronological and any(t.get("code") == code and t.get("date", "") > day for t in trades):
                raise TradeError("请按成交日期顺序补录，不能将更早成交直接应用到当前持仓")
            portfolio = _read_json(self.portfolio_path, {"holdings": [], "last_refresh": None})
            portfolio.setdefault("holdings", [])
            state_raw = _read_json(self.workflow.state_file, {})
            state = {
                "schema_version": SCHEMA_VERSION,
                "updated_at": state_raw.get("updated_at"),
                "holdings": _normalize_items(state_raw.get("holdings")),
                "cleared": _normalize_items(state_raw.get("cleared")),
                "policy": state_raw.get("policy") or DEFAULT_POLICY,
            }
            resolved_name = str(name or "").strip() or next(
                (item["name"] for item in state["holdings"] if item["code"] == code),
                code,
            )

            existing = next((item for item in portfolio["holdings"] if item.get("code") == code), None)
            if cost_value is None:
                if existing is None:
                    raise TradeError("本地没有该证券持仓，不能从工作台补录卖出；请先核对期初持仓")
                cost_value = _decimal(existing.get("cost"), "本地持仓成本")
                close_position = Decimal(str(existing.get("shares", 0))) == quantity
            position_after = None
            if existing is not None:
                current_shares = Decimal(str(existing.get("shares", 0)))
                if current_shares < quantity:
                    raise TradeError(f"本地持仓数量不足：现有{_quantity(float(current_shares))}股")
                remaining = current_shares - Decimal(quantity)
                if remaining == 0:
                    portfolio["holdings"].remove(existing)
                else:
                    existing["shares"] = int(remaining) if remaining == remaining.to_integral_value() else float(remaining)
                    position_after = {
                        "code": code,
                        "name": resolved_name,
                        "shares": existing["shares"],
                        "cost": existing.get("cost"),
                    }

            if close_position:
                state["holdings"] = [item for item in state["holdings"] if item["code"] != code]
                if all(item["code"] != code for item in state["cleared"]):
                    state["cleared"].append({"code": code, "name": resolved_name})
                if existing is not None and position_after is not None:
                    raise TradeError("标记清仓时，卖出数量必须等于本地已知持仓数量")
            state["updated_at"] = _now_iso()

            day_json, day_markdown = self.workflow._day_paths(day)
            day_payload = _read_json(day_json, {}) if day_json.exists() else self.workflow._new_day(day)
            day_payload["holdings_snapshot"] = list(state["holdings"])
            day_payload["cleared_snapshot"] = list(state["cleared"])
            day_payload["state_updated_at"] = state["updated_at"]
            day_payload["updated_at"] = _now_iso()

            amount = _money(Decimal(quantity) * price_value)
            pnl = _money(Decimal(quantity) * (price_value - cost_value))
            pnl_pct = float(((price_value - cost_value) / cost_value * 100).quantize(Decimal("0.01")))
            trade = {
                "id": identity,
                "side": "sell",
                "date": day,
                "reported_at": timestamp,
                "code": code,
                "name": resolved_name,
                "quantity": quantity,
                "price": float(price_value),
                "cost": float(cost_value),
                "amount": float(amount),
                "pnl": float(pnl),
                "pnl_pct": pnl_pct,
                "close_position": close_position,
                "position_after": position_after,
            }
            portfolio.setdefault("realized_trades", []).append(trade)
            day_payload.setdefault("trades", []).append(trade)
            trades.append(trade)
            trade_log["schema_version"] = TRADE_SCHEMA_VERSION

            ledger = self.ledger_path.read_text(encoding="utf-8") if self.ledger_path.exists() else _default_ledger()
            updates = {
                self.portfolio_path: _json_text(portfolio).encode("utf-8"),
                self.workflow.state_file: _json_text(state).encode("utf-8"),
                day_json: _json_text(day_payload).encode("utf-8"),
                day_markdown: self.workflow.render_markdown(day_payload).encode("utf-8"),
                self.ledger_path: _update_sell_ledger(ledger, trade, position_after).encode("utf-8"),
                self.trades_path: _json_text(trade_log).encode("utf-8"),
            }
            if not dry_run:
                try:
                    _atomic_batch(updates, replace=self._replace)
                except OSError as exc:
                    raise TradeError(f"交易记账失败，已回滚：{exc}") from exc

        return {
            "ok": True,
            "action": "sell",
            "trade_id": identity,
            "already_recorded": False,
            "dry_run": dry_run,
            "trade": trade,
            "holding_count": len(state["holdings"]),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
