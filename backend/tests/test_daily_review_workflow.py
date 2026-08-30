"""每日复盘工作流：全离线验证私人状态、历史快照、提示词和归档。"""

import json

import pytest

from daily_review import ReviewWorkflow, ReviewWorkflowError


HOLDINGS = [
    {"code": "588200", "name": "科创芯片ETF"},
    {"code": "512100", "name": "中证1000ETF"},
]


def test_replace_universe_deduplicates_and_current_wins(tmp_path):
    workflow = ReviewWorkflow(tmp_path)
    state = workflow.replace_universe(
        HOLDINGS + [{"code": "588200", "name": "重复项"}],
        [{"code": "588200", "name": "不应清仓"}, {"code": "515050", "name": "已清仓"}],
    )
    assert [item["code"] for item in state["holdings"]] == ["588200", "512100"]
    assert state["cleared"] == [{"code": "515050", "name": "已清仓"}]
    assert json.loads(workflow.state_file.read_text(encoding="utf-8"))["schema_version"] == 1


def test_invalid_code_is_rejected(tmp_path):
    workflow = ReviewWorkflow(tmp_path)
    with pytest.raises(ReviewWorkflowError, match="无效证券代码"):
        workflow.replace_universe([{"code": "ABC", "name": "坏代码"}])


def test_prepare_is_idempotent_and_freezes_snapshot(tmp_path):
    workflow = ReviewWorkflow(tmp_path)
    workflow.replace_universe(HOLDINGS)
    first, created, markdown = workflow.prepare_day("2026-08-05")
    assert created is True and markdown.exists()
    assert [item["code"] for item in first["holdings_snapshot"]] == ["588200", "512100"]

    workflow.replace_universe([{"code": "159937", "name": "黄金ETF"}])
    second, created_again, _ = workflow.prepare_day("2026-08-05")
    assert created_again is False
    assert [item["code"] for item in second["holdings_snapshot"]] == ["588200", "512100"]


def test_prompt_contains_phase_policy_and_privacy_gate(tmp_path):
    workflow = ReviewWorkflow(tmp_path)
    workflow.replace_universe(HOLDINGS, [{"code": "515050", "name": "通信ETF"}])
    prompt = workflow.build_prompt("premarket", "2026-08-05")
    assert "2026-08-05 盘前复盘" in prompt
    assert "588200 科创芯片ETF" in prompt
    assert "515050 通信ETF" in prompt
    assert "只发送代码、不发送数量和成本" in prompt
    assert "外盘只作波动与开盘过滤器" in prompt


def test_record_phase_updates_json_and_markdown(tmp_path):
    workflow = ReviewWorkflow(tmp_path)
    workflow.replace_universe(HOLDINGS)
    payload, markdown = workflow.record_phase(
        "close",
        "今日为成长风格修复。",
        "2026-08-05",
        data_asof="2026-08-05T15:10+08:00",
        source_status="partial",
        source_notes=["资讯雷达失败，未沿用旧缓存"],
    )
    phase = payload["phases"]["close"]
    assert phase["status"] == "completed"
    assert phase["source_status"] == "partial"
    rendered = markdown.read_text(encoding="utf-8")
    assert "今日为成长风格修复。" in rendered
    assert "资讯雷达失败，未沿用旧缓存" in rendered
    assert "## 盘后复盘" in rendered


def test_invalid_phase_status_and_date_are_rejected(tmp_path):
    workflow = ReviewWorkflow(tmp_path)
    workflow.replace_universe(HOLDINGS)
    with pytest.raises(ReviewWorkflowError, match="未知复盘阶段"):
        workflow.build_prompt("night", "2026-08-05")
    with pytest.raises(ReviewWorkflowError, match="未知数据源状态"):
        workflow.record_phase("close", "x", "2026-08-05", source_status="maybe")
    with pytest.raises(ReviewWorkflowError, match="日期格式"):
        workflow.prepare_day("2026/08/05")
