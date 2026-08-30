"""统一 trade buy 命令：离线验证多文件同步、幂等和失败回滚。"""

import json
import os

import pytest

from daily_review import ReviewWorkflow
from trade_service import TradeError, TradeService


def _setup(tmp_path):
    data_dir = tmp_path / "data"
    ledger = tmp_path / "交易台账.md"
    workflow = ReviewWorkflow(data_dir / "daily-review")
    workflow.replace_universe(
        [{"code": "512100", "name": "中证1000ETF"}],
        [{"code": "603228", "name": "历史清仓项"}],
    )
    workflow.prepare_day("2026-08-05")
    (data_dir / "portfolio.json").write_text(
        json.dumps(
            {"holdings": [{"code": "512100", "shares": 21000, "cost": 2.905}], "last_refresh": None},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ledger.write_text(
        """# 交易台账（私有，不进仓库）

## 当前持仓

| 开仓日 | 标的 | 方向 | 数量 | 均价 | 成本额 | 关联研究 |
|---|---|---|---|---|---|---|
| 2026-07-17 | 512100 中证1000ETF南方 | 买入 | 21,000 | 2.905 | ¥61,005 | 历史研究 |

## 决策记录

### 历史记录
- 保留我。

## 平仓记录

（无）
""",
        encoding="utf-8",
    )
    return data_dir, ledger, workflow


def test_buy_updates_all_local_stores_and_day_markdown(tmp_path):
    data_dir, ledger, workflow = _setup(tmp_path)
    service = TradeService(data_dir, ledger)

    result = service.buy(
        "603228",
        name="景旺电子",
        quantity=1000,
        price="76.46",
        trade_date="2026-08-05",
        reported_at="2026-08-05 09:56+08:00",
        trade_id="buy-603228-20260805-0956",
    )

    assert result["ok"] is True
    assert result["holding_count"] == 2
    assert result["position"] == {"code": "603228", "name": "景旺电子", "shares": 1000, "cost": 76.46}

    portfolio = json.loads((data_dir / "portfolio.json").read_text(encoding="utf-8"))
    assert portfolio["holdings"][-1] == {"code": "603228", "shares": 1000, "cost": 76.46}

    state = json.loads(workflow.state_file.read_text(encoding="utf-8"))
    assert state["holdings"][-1] == {"code": "603228", "name": "景旺电子"}
    assert all(item["code"] != "603228" for item in state["cleared"])

    day = workflow.load_day("2026-08-05")
    assert day["holdings_snapshot"][-1]["code"] == "603228"
    assert day["trades"][0]["amount"] == 76460.0
    markdown = (workflow.days_dir / "2026-08-05.md").read_text(encoding="utf-8")
    assert "## 当日交易" in markdown
    assert "buy-603228-20260805-0956" in markdown
    assert "景旺电子" in markdown

    ledger_text = ledger.read_text(encoding="utf-8")
    assert "| 2026-08-05 | 603228 景旺电子 | 买入 | 1,000 | 76.46 | ¥76,460 |" in ledger_text
    assert "### 历史记录" in ledger_text
    assert "<!-- trade-id:buy-603228-20260805-0956 -->" in ledger_text

    trade_log = json.loads((data_dir / "trades.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in trade_log["trades"]] == ["buy-603228-20260805-0956"]


def test_buy_existing_position_uses_weighted_average_cost(tmp_path):
    data_dir, ledger, _ = _setup(tmp_path)
    portfolio_path = data_dir / "portfolio.json"
    portfolio_path.write_text(
        json.dumps({"holdings": [{"code": "603228", "shares": 100, "cost": 10.0}]}),
        encoding="utf-8",
    )
    service = TradeService(data_dir, ledger)

    result = service.buy(
        "603228",
        name="景旺电子",
        quantity=100,
        price="12",
        trade_date="2026-08-05",
        trade_id="weighted-buy",
    )

    assert result["position"]["shares"] == 200
    assert result["position"]["cost"] == 11.0
    ledger_text = ledger.read_text(encoding="utf-8")
    assert "| 200 | 11 | ¥2,200 |" in ledger_text


def test_same_trade_id_is_idempotent(tmp_path):
    data_dir, ledger, workflow = _setup(tmp_path)
    service = TradeService(data_dir, ledger)
    kwargs = {
        "name": "景旺电子",
        "quantity": 1000,
        "price": "76.46",
        "trade_date": "2026-08-05",
        "trade_id": "same-buy",
    }

    first = service.buy("603228", **kwargs)
    second = service.buy("603228", **kwargs)

    assert first["already_recorded"] is False
    assert second["already_recorded"] is True
    portfolio = json.loads((data_dir / "portfolio.json").read_text(encoding="utf-8"))
    position = next(item for item in portfolio["holdings"] if item["code"] == "603228")
    assert position["shares"] == 1000
    assert len(workflow.load_day("2026-08-05")["trades"]) == 1
    assert ledger.read_text(encoding="utf-8").count("trade-id:same-buy") == 1


def test_conflicting_trade_id_is_rejected(tmp_path):
    data_dir, ledger, _ = _setup(tmp_path)
    service = TradeService(data_dir, ledger)
    service.buy("603228", name="景旺电子", quantity=1000, price="76.46", trade_id="conflict")
    with pytest.raises(TradeError, match="交易ID冲突"):
        service.buy("603228", name="景旺电子", quantity=2000, price="76.46", trade_id="conflict")


def test_dry_run_does_not_change_target_files(tmp_path):
    data_dir, ledger, workflow = _setup(tmp_path)
    targets = [data_dir / "portfolio.json", workflow.state_file, *workflow._day_paths("2026-08-05"), ledger]
    before = {path: path.read_bytes() for path in targets}

    result = TradeService(data_dir, ledger).buy(
        "603228",
        name="景旺电子",
        quantity=1000,
        price="76.46",
        trade_date="2026-08-05",
        trade_id="dry-run",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert {path: path.read_bytes() for path in targets} == before
    assert not (data_dir / "trades.json").exists()


def test_replace_failure_rolls_back_every_committed_target(tmp_path):
    data_dir, ledger, workflow = _setup(tmp_path)
    targets = [data_dir / "portfolio.json", workflow.state_file, *workflow._day_paths("2026-08-05"), ledger]
    before = {path: path.read_bytes() for path in targets}
    calls = 0

    def fail_once_on_third_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated replace failure")
        os.replace(source, destination)

    service = TradeService(data_dir, ledger, replace=fail_once_on_third_replace)
    with pytest.raises(TradeError, match="已回滚"):
        service.buy(
            "603228",
            name="景旺电子",
            quantity=1000,
            price="76.46",
            trade_date="2026-08-05",
            trade_id="rollback-buy",
        )

    assert {path: path.read_bytes() for path in targets} == before
    assert not (data_dir / "trades.json").exists()


def test_partial_sell_records_gross_pnl_and_keeps_code_holding(tmp_path):
    data_dir, ledger, workflow = _setup(tmp_path)
    workflow.replace_universe(
        [
            {"code": "512100", "name": "中证1000ETF"},
            {"code": "603823", "name": "百合花"},
        ]
    )
    service = TradeService(data_dir, ledger)

    result = service.sell(
        "603823",
        name="百合花",
        quantity=1000,
        price="60.73",
        cost="54.43",
        trade_date="2026-08-05",
        trade_id="sell-baihehua",
    )

    assert result["trade"]["pnl"] == 6300.0
    assert result["trade"]["pnl_pct"] == 11.57
    state = json.loads(workflow.state_file.read_text(encoding="utf-8"))
    assert any(item["code"] == "603823" for item in state["holdings"])
    assert all(item["code"] != "603823" for item in state["cleared"])
    portfolio = json.loads((data_dir / "portfolio.json").read_text(encoding="utf-8"))
    assert portfolio["realized_trades"][0]["pnl"] == 6300.0
    assert "部分卖出 603823 @60.73" in ledger.read_text(encoding="utf-8")
