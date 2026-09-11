import pytest

from market_ingest import BaoStockError, BaoStockSource


class Result:
    def __init__(self, fields, rows, error_code="0", error_msg=""):
        self.fields = fields
        self.rows = rows
        self.error_code = error_code
        self.error_msg = error_msg
        self.index = 0

    def next(self):
        if self.index >= len(self.rows):
            return False
        self.index += 1
        return True

    def get_row_data(self):
        return self.rows[self.index - 1]


class FakeBaoStock:
    def __init__(self):
        self.logged_out = False

    def login(self):
        return Result([], [])

    def logout(self):
        self.logged_out = True

    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        names = fields.split(",")
        raw = [
            "2026-09-10", code, "9.8", "10.5", "9.5", "10", "9.7",
            "1000", "10000", adjustflag, "1.2", "1", "3.1", "0",
        ]
        qfq = [
            "2026-09-10", code, "4.9", "5.25", "4.75", "5", "4.85",
            "1000", "10000", adjustflag, "1.2", "1", "3.1", "0",
        ]
        return Result(names, [qfq if adjustflag == "2" else raw])


def test_fetch_symbol_keeps_raw_amount_and_derives_qfq_factor():
    module = FakeBaoStock()
    with BaoStockSource(module=module) as source:
        result = source.fetch_symbol("sh.600001", "2026-09-01", "2026-09-11")

    assert module.logged_out is True
    assert len(result["bars"]) == 1
    assert result["bars"][0]["amount_cny"] == 10_000
    assert result["bars"][0]["volume_shares"] == 1_000
    assert result["bars"][0]["is_st"] is False
    assert result["factors"][0]["qfq_factor"] == pytest.approx(0.5)


def test_fetch_symbol_rejects_date_mismatch_between_raw_and_qfq():
    module = FakeBaoStock()
    original = module.query_history_k_data_plus

    def mismatch(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs["adjustflag"] == "2":
            result.rows[0][0] = "2026-09-11"
        return result

    module.query_history_k_data_plus = mismatch
    with BaoStockSource(module=module) as source:
        with pytest.raises(BaoStockError, match="日期"):
            source.fetch_symbol("sh.600001", "2026-09-01", "2026-09-11")


def test_baostock_error_code_is_not_treated_as_empty_success():
    module = FakeBaoStock()

    def failed(*args, **kwargs):
        return Result([], [], error_code="100", error_msg="source failed")

    module.query_history_k_data_plus = failed
    with BaoStockSource(module=module) as source:
        with pytest.raises(BaoStockError, match="source failed"):
            source.fetch_symbol("sh.600001", "2026-09-01", "2026-09-11")


def test_history_reconnects_after_transient_source_error(monkeypatch):
    module = FakeBaoStock()
    original = module.query_history_k_data_plus
    calls = 0
    monkeypatch.setattr("market_ingest.time.sleep", lambda _: None)

    def flaky(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Result([], [], error_code="10002007", error_msg="network error")
        return original(*args, **kwargs)

    module.query_history_k_data_plus = flaky
    with BaoStockSource(module=module, retries=2) as source:
        result = source.fetch_symbol("sh.600001", "2026-09-01", "2026-09-11")

    assert calls == 3
    assert len(result["bars"]) == 1
