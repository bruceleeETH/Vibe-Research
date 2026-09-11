from market_universe import build_current_universe, is_mainboard_code


def row(code, name="测试股份", mcap=5_000_000_000, price=10):
    return {
        "code": code,
        "name": name,
        "mcap": mcap,
        "price": price,
        "secid": ("1." if code.startswith("6") else "0.") + code,
    }


def test_mainboard_code_rules_exclude_other_boards_and_funds():
    for code in ("600001", "601001", "603001", "605001", "000001", "001001", "002001", "003001"):
        assert is_mainboard_code(code)
    for code in ("300001", "301001", "688001", "920001", "510300", "159915"):
        assert not is_mainboard_code(code)
    # 指数与股票代码段会重叠；证券类型由上游股票快照保证，不能仅凭代码判别 000300。
    assert is_mainboard_code("000300")


def test_current_universe_excludes_st_retiring_small_and_missing_mcap():
    rows = [
        row("600001"),
        row("600002", "ST测试"),
        row("600003", "测试退"),
        row("600004", mcap=2_999_999_999),
        row("600005", mcap=None),
        row("600006", price=None),
        row("300001"),
    ]

    result = build_current_universe(rows, "2026-09-11", min_mcap=3_000_000_000)

    assert [item["code"] for item in result["eligible"]] == ["600001"]
    assert result["counts"] == {
        "snapshot": 7,
        "mainboard": 6,
        "eligible": 1,
        "st_or_retiring": 2,
        "not_listed_or_no_quote": 1,
        "below_mcap": 1,
        "missing_mcap": 1,
    }
    reasons = {item["code"]: item["exclusion_reason"] for item in result["universe_rows"]}
    assert reasons["600002"] == "st_or_retiring"
    assert reasons["600004"] == "below_mcap"
    assert reasons["600005"] == "missing_mcap"
    assert reasons["600006"] == "not_listed_or_no_quote"


def test_market_cap_boundary_is_inclusive():
    result = build_current_universe(
        [row("000001", mcap=3_000_000_000)],
        "2026-09-11",
        min_mcap=3_000_000_000,
    )

    assert len(result["eligible"]) == 1
    assert result["universe_rows"][0]["eligible"] is True
    assert result["market_cap_asof"] == "2026-09-11"
    assert result["universe_mode"] == "current_snapshot"
