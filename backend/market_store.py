"""DuckDB 本地主板行情仓：单写者、版本化提交、只读分析查询。"""
from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import fcntl
except ImportError:  # pragma: no cover - 当前项目主要运行于 macOS/Linux
    fcntl = None

import duckdb


TZ = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 1


class StoreValidationError(ValueError):
    """采集批次违反规范化行情契约。"""


class MarketStore:
    """管理本地 DuckDB 行情库；写操作必须经过进程级文件锁。"""

    def __init__(self, data_root: str | Path | None = None):
        if data_root is None:
            data_root = Path(os.environ.get("VR_DATA_DIR", Path.home() / ".vibe-research")) / "market-data"
        self.root = Path(data_root)
        self.path = self.root / "market.duckdb"
        self.lock_path = self.root / "update.lock"

    @contextmanager
    def _writer(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a") as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _create_schema(connection) -> None:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS store_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL
            );
            INSERT OR IGNORE INTO store_meta VALUES ('schema_version', '1');
            INSERT OR IGNORE INTO store_meta VALUES ('active_revision', '0');

            CREATE TABLE IF NOT EXISTS instruments (
                symbol VARCHAR PRIMARY KEY,
                code VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                board VARCHAR NOT NULL,
                name_current VARCHAR NOT NULL,
                list_date DATE,
                delist_date DATE,
                revision BIGINT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS universe_daily (
                trade_date DATE NOT NULL,
                symbol VARCHAR NOT NULL,
                name_asof VARCHAR NOT NULL,
                is_st BOOLEAN NOT NULL,
                trade_status VARCHAR NOT NULL,
                total_mcap_cny DOUBLE,
                eligible BOOLEAN NOT NULL,
                exclusion_reason VARCHAR NOT NULL,
                ingest_run_id VARCHAR NOT NULL,
                revision BIGINT NOT NULL,
                PRIMARY KEY (trade_date, symbol)
            );

            CREATE TABLE IF NOT EXISTS daily_bars (
                trade_date DATE NOT NULL,
                symbol VARCHAR NOT NULL,
                open_raw DOUBLE NOT NULL,
                high_raw DOUBLE NOT NULL,
                low_raw DOUBLE NOT NULL,
                close_raw DOUBLE NOT NULL,
                preclose_raw DOUBLE,
                volume_shares DOUBLE,
                amount_cny DOUBLE,
                turnover_pct DOUBLE,
                trade_status VARCHAR NOT NULL,
                is_st BOOLEAN NOT NULL,
                source VARCHAR NOT NULL,
                ingest_run_id VARCHAR NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                revision BIGINT NOT NULL,
                PRIMARY KEY (trade_date, symbol)
            );

            CREATE TABLE IF NOT EXISTS adjust_factors (
                trade_date DATE NOT NULL,
                symbol VARCHAR NOT NULL,
                qfq_factor DOUBLE NOT NULL,
                source VARCHAR NOT NULL,
                ingest_run_id VARCHAR NOT NULL,
                revision BIGINT NOT NULL,
                PRIMARY KEY (trade_date, symbol)
            );

            CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id VARCHAR PRIMARY KEY,
                revision BIGINT,
                source VARCHAR NOT NULL,
                scope VARCHAR NOT NULL,
                as_of DATE NOT NULL,
                status VARCHAR NOT NULL,
                instrument_rows BIGINT NOT NULL DEFAULT 0,
                universe_rows BIGINT NOT NULL DEFAULT 0,
                bar_rows BIGINT NOT NULL DEFAULT 0,
                factor_rows BIGINT NOT NULL DEFAULT 0,
                error VARCHAR,
                summary_json VARCHAR,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS quality_issues (
                run_id VARCHAR NOT NULL,
                symbol VARCHAR,
                trade_date DATE,
                issue_code VARCHAR NOT NULL,
                detail VARCHAR NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            );
        """)

    def initialize(self) -> None:
        """幂等初始化数据库 schema。"""
        with self._writer():
            connection = duckdb.connect(str(self.path))
            try:
                self._create_schema(connection)
            finally:
                connection.close()

    @staticmethod
    def _validate(as_of: str, instruments: list[dict], universe_rows: list[dict],
                  bars: list[dict], factors: list[dict]) -> None:
        cutoff = date.fromisoformat(as_of)
        symbols = {row["symbol"] for row in instruments}
        if len(symbols) != len(instruments):
            raise StoreValidationError("证券列表存在重复 symbol")
        factor_map = {}
        for row in factors:
            key = (row["symbol"], date.fromisoformat(row["trade_date"]))
            if key in factor_map:
                raise StoreValidationError("复权因子存在重复日期")
            factor = float(row["qfq_factor"])
            if not math.isfinite(factor) or factor <= 0:
                raise StoreValidationError("复权因子必须为正有限值")
            factor_map[key] = factor

        seen = set()
        for row in bars:
            day = date.fromisoformat(row["trade_date"])
            key = (row["symbol"], day)
            if key in seen:
                raise StoreValidationError("日线存在重复日期")
            seen.add(key)
            if row["symbol"] not in symbols:
                raise StoreValidationError("日线证券不在 instruments 中")
            if day > cutoff:
                raise StoreValidationError("日线日期晚于批次 as_of")
            values = [float(row[name]) for name in ("open_raw", "high_raw", "low_raw", "close_raw")]
            if not all(math.isfinite(value) and value > 0 for value in values):
                raise StoreValidationError("OHLC 必须为正有限值")
            open_, high, low, close = values
            if not low <= min(open_, close) <= max(open_, close) <= high:
                raise StoreValidationError("OHLC 区间关系无效")
            volume = row.get("volume_shares")
            amount = row.get("amount_cny")
            if volume is not None and (not math.isfinite(float(volume)) or float(volume) < 0):
                raise StoreValidationError("成交股数无效")
            if amount is not None and (not math.isfinite(float(amount)) or float(amount) < 0):
                raise StoreValidationError("成交额无效")
            if amount is not None and float(amount) > 0 and (volume is None or float(volume) <= 0):
                raise StoreValidationError("正成交额缺少成交股数")
            factor = factor_map.get(key)
            if factor is None:
                raise StoreValidationError("日线缺少同日复权因子")
            if amount is not None and volume is not None and float(volume) > 0:
                vwap_qfq = float(amount) / float(volume) * factor
                tolerance = max(0.02, high * factor * 0.001)
                if not low * factor - tolerance <= vwap_qfq <= high * factor + tolerance:
                    raise StoreValidationError("前复权全天均价超出 OHLC 区间")

        universe_seen = set()
        for row in universe_rows:
            key = (row["symbol"], date.fromisoformat(row["trade_date"]))
            if key in universe_seen:
                raise StoreValidationError("股票池存在重复日期")
            universe_seen.add(key)
            if key[1] > cutoff:
                raise StoreValidationError("股票池日期晚于批次 as_of")

    def commit_ingest(self, source: str, as_of: str, scope: str,
                      instruments: list[dict], universe_rows: list[dict],
                      bars: list[dict], factors: list[dict],
                      summary: dict | None = None) -> dict:
        """校验并原子合并一个采集批次；失败不推进 active revision。"""
        run_id = str(uuid.uuid4())
        started_at = datetime.now(TZ)
        with self._writer():
            connection = duckdb.connect(str(self.path))
            try:
                self._create_schema(connection)
                connection.execute(
                    "INSERT INTO ingest_runs(run_id,source,scope,as_of,status,started_at) VALUES (?,?,?,?,?,?)",
                    [run_id, source, scope, as_of, "running", started_at],
                )
                try:
                    self._validate(as_of, instruments, universe_rows, bars, factors)
                except Exception as exc:
                    connection.execute(
                        "UPDATE ingest_runs SET status='failed',error=?,finished_at=? WHERE run_id=?",
                        [str(exc)[:1000], datetime.now(TZ), run_id],
                    )
                    raise

                revision = int(connection.execute(
                    "SELECT value FROM store_meta WHERE key='active_revision'"
                ).fetchone()[0]) + 1
                observed_at = datetime.now(TZ)
                try:
                    connection.begin()
                    if instruments:
                        connection.executemany("""
                            INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?,?,?)
                        """, [[
                            row["symbol"], row["code"], row["exchange"], row["board"],
                            row["name_current"], row.get("list_date"), row.get("delist_date"), revision,
                        ] for row in instruments])
                    if universe_rows:
                        connection.executemany("""
                            INSERT OR REPLACE INTO universe_daily VALUES (?,?,?,?,?,?,?,?,?,?)
                        """, [[
                            row["trade_date"], row["symbol"], row["name_asof"], bool(row["is_st"]),
                            str(row["trade_status"]), row.get("total_mcap_cny"), bool(row["eligible"]),
                            row.get("exclusion_reason", ""), run_id, revision,
                        ] for row in universe_rows])
                    if bars:
                        connection.executemany("""
                            INSERT OR REPLACE INTO daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, [[
                            row["trade_date"], row["symbol"], row["open_raw"], row["high_raw"],
                            row["low_raw"], row["close_raw"], row.get("preclose_raw"),
                            row.get("volume_shares"), row.get("amount_cny"), row.get("turnover_pct"),
                            str(row.get("trade_status", "")), bool(row.get("is_st", False)),
                            source, run_id, observed_at, revision,
                        ] for row in bars])
                    if factors:
                        connection.executemany("""
                            INSERT OR REPLACE INTO adjust_factors VALUES (?,?,?,?,?,?)
                        """, [[
                            row["trade_date"], row["symbol"], row["qfq_factor"],
                            source, run_id, revision,
                        ] for row in factors])
                    connection.execute(
                        "UPDATE store_meta SET value=? WHERE key='active_revision'",
                        [str(revision)],
                    )
                    connection.execute("""
                        UPDATE ingest_runs SET revision=?,status='success',
                            instrument_rows=?,universe_rows=?,bar_rows=?,factor_rows=?,
                            summary_json=?,finished_at=? WHERE run_id=?
                    """, [
                        revision, len(instruments), len(universe_rows), len(bars), len(factors),
                        json.dumps(summary or {}, ensure_ascii=False), datetime.now(TZ), run_id,
                    ])
                    connection.commit()
                except Exception as exc:
                    connection.rollback()
                    connection.execute(
                        "UPDATE ingest_runs SET status='failed',error=?,finished_at=? WHERE run_id=?",
                        [str(exc)[:1000], datetime.now(TZ), run_id],
                    )
                    raise
                return {
                    "run_id": run_id,
                    "revision": revision,
                    "instrument_rows": len(instruments),
                    "universe_rows": len(universe_rows),
                    "bar_rows": len(bars),
                    "factor_rows": len(factors),
                }
            finally:
                connection.close()

    def status(self) -> dict:
        """返回当前版本、覆盖日期和记录数量。"""
        if not self.path.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "active_revision": 0,
                "instruments": 0,
                "eligible_symbols": 0,
                "bar_symbols": 0,
                "bars": 0,
                "min_date": None,
                "max_date": None,
                "failed_runs": 0,
                "path": str(self.path),
            }
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            revision = int(connection.execute(
                "SELECT value FROM store_meta WHERE key='active_revision'"
            ).fetchone()[0])
            min_date, max_date, bars = connection.execute(
                "SELECT min(trade_date),max(trade_date),count(*) FROM daily_bars"
            ).fetchone()
            latest_universe = connection.execute("SELECT max(trade_date) FROM universe_daily").fetchone()[0]
            eligible = 0 if latest_universe is None else connection.execute(
                "SELECT count(*) FROM universe_daily WHERE trade_date=? AND eligible",
                [latest_universe],
            ).fetchone()[0]
            return {
                "schema_version": SCHEMA_VERSION,
                "active_revision": revision,
                "instruments": connection.execute("SELECT count(*) FROM instruments").fetchone()[0],
                "eligible_symbols": eligible,
                "bar_symbols": connection.execute(
                    "SELECT count(DISTINCT symbol) FROM daily_bars"
                ).fetchone()[0],
                "bars": bars,
                "min_date": min_date.isoformat() if min_date else None,
                "max_date": max_date.isoformat() if max_date else None,
                "failed_runs": connection.execute(
                    "SELECT count(*) FROM ingest_runs WHERE status='failed'"
                ).fetchone()[0],
                "path": str(self.path),
            }
        finally:
            connection.close()

    def bars(self, codes: list[str], start: str, end: str) -> list[dict]:
        """按代码与日期查询原始/前复权价格及全天均价。"""
        if not self.path.exists() or not codes:
            return []
        symbols = [
            ("sh." if str(code).startswith("6") else "sz.") + str(code)
            if "." not in str(code) else str(code)
            for code in codes
        ]
        placeholders = ",".join("?" for _ in symbols)
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            cursor = connection.execute(f"""
                SELECT b.trade_date,b.symbol,b.open_raw,b.high_raw,b.low_raw,b.close_raw,
                       b.preclose_raw,b.volume_shares,b.amount_cny,b.turnover_pct,
                       b.trade_status,b.is_st,f.qfq_factor,
                       b.open_raw*f.qfq_factor AS open_qfq,
                       b.high_raw*f.qfq_factor AS high_qfq,
                       b.low_raw*f.qfq_factor AS low_qfq,
                       b.close_raw*f.qfq_factor AS close_qfq,
                       CASE WHEN b.volume_shares>0 AND b.amount_cny>=0
                            THEN b.amount_cny/b.volume_shares*f.qfq_factor END AS vwap_qfq
                FROM daily_bars b
                JOIN adjust_factors f USING(trade_date,symbol)
                WHERE b.symbol IN ({placeholders}) AND b.trade_date BETWEEN ? AND ?
                ORDER BY b.symbol,b.trade_date
            """, [*symbols, start, end])
            names = [column[0] for column in cursor.description]
            return [
                {
                    name: value.isoformat() if isinstance(value, date) else value
                    for name, value in zip(names, row)
                }
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()
