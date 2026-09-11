# 主板非 ST 可复用历史数据层 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将趋势策略验证从 15 只观察池扩展到总市值不低于 30 亿元的沪深主板非 ST 股票，先建立 3 个月分析窗口，并建设可增量更新、可复现、可供后续策略复用的本地历史数据层。

**Architecture:** 使用 DuckDB 保存规范化证券、日线、股票池快照、特征与研究运行记录；原始行情采用不复权价格和实际成交额，复权因子单独保存，查询时生成前复权价格与前复权全天均价。Baostock 作为历史主源，腾讯作为最新行情和抽样交叉验证源，东财全市场快照用于当前证券池发现。按单写者、事务提交、失败不覆盖的方式更新；定期导出 Parquet 作为可移植备份。

**Tech Stack:** Python 3.12+、DuckDB、Baostock、FastAPI、React 19、TypeScript、pytest、Node test runner。

---

## 实施状态（2026-09-12）

- 已完成 DuckDB schema v2、追加式 revision、跨进程共享读锁/独占写锁及 v1 样本库迁移。
- 已完成当前主板非 ST、总市值不低于 30 亿元且已有交易行情的股票池：2,687 只。
- 已回填 3 个月分析窗口 + 30 个交易日预热，共 96 个交易日、257,492 根日线。
- 11 只新股因上市不足 96 日而自然少行，共少 460 行；不属于采集失败。
- 历史数据保留 1,244 条信号日 ST 状态和 232 条停牌状态，供服务端按日期排除。
- 前复权因子范围 0.664669–1.0；全天均价越界 0；失败 ingest run 为 0。
- DuckDB 约 41 MB；revision 108 的 Parquet 导出约 12 MB。
- 已提供 `status`、`dates`、`universe`、`bars`、`trend-snapshot` 只读 API；趋势页按日期分页读取全主板结果。
- 尚未完成正式历史时点总市值重建；当前页面明确标记 `universe_mode=current_snapshot`，只用于数据与规则验证。

## 1. 需求与边界

### 1.1 首期范围

- 市场：沪深主板。
- 代码范围：
  - 上海主板：`600`、`601`、`603`、`605`。
  - 深圳主板：`000`、`001`、`002`、`003`。
- 当前页面默认股票池：查询日 `is_st = false`、非退市整理、总市值不低于 30 亿元、已上市、存在有效日线。
- 当前实查规模（2026-09-11）：全 A 快照 5,913 只，主板 3,487 只，按当前名称排除 ST/退市整理后 3,116 只；其中总市值不低于 30 亿元且已有有效行情 2,687 只，低于门槛 364 只，市值缺失 64 只，另有沈鼓集团 `601091` 尚处发行阶段、没有交易行情。
- 市值缺失不得按 0 或“默认合格”处理：首期保守排除，并在覆盖率报告中单列。
- 首期分析窗口：最近 3 个自然月；另外向前采集至少 30 个交易日作为指标预热，预热期只参与特征计算、不计入策略结果。
- 首期频率：日线；不采集分钟线、逐笔和 L2。
- 首期字段：开高低收、前收、成交股数、成交额、换手率、交易状态、当日 ST 状态、复权因子、来源与采集批次。
- 页面功能：按日期查看主板非 ST 条件命中、隔日开低高均收、数据覆盖率和失败原因。

### 1.2 不纳入首期

- 创业板、科创板、北交所、ETF、港美股。
- 自动下单、仓位建议或收益承诺。
- 盘中实时信号和 14:40 模拟成交。
- 新闻、题材热度和主力资金历史回放。
- 自动参数寻优。

### 1.3 回测口径

“非 ST”和“总市值不低于 30 亿元”原则上都必须按**信号发生日**判断，不能拿今天的名称或市值过滤全部历史。历史回测必须保留后来退市、后来 ST、后来更名和后来跌破市值门槛的证券，避免幸存者偏差。

首期 3 个月 MVP 暂以 2026-09-11 当前快照筛出的 2,687 只已交易证券作为固定采集清单，并明确标记 `universe_mode=current_snapshot`、`market_cap_asof=2026-09-11`。该模式只用于验证采集、存储、查询和页面，不得作为无偏历史回测结论。正式研究必须切换到 `universe_mode=point_in_time`。

## 2. 关键架构决策

### ADR-001：DuckDB 为规范化主库，Parquet 为交换与备份格式

**决定**

- 主库：`~/.vibe-research/market-data/market.duckdb`
- 数据清单：`~/.vibe-research/market-data/manifests/`
- 失败隔离：`~/.vibe-research/market-data/quarantine/`
- Parquet 导出：`~/.vibe-research/market-data/exports/`
- 更新锁：`~/.vibe-research/market-data/update.lock`

**原因**

- 约 3,116 只股票 × 250 个交易日约 78 万行/年；五年约 390 万行。
- JSON 适合 15 只页面快照，不适合全市场筛选、跨年聚合和增量覆盖。
- SQLite 零依赖且事务可靠，但按列扫描、窗口函数和导出分析不如 DuckDB。
- 纯 Parquet 紧凑且通用，但增量更新、唯一约束和运行账本需要额外协调。
- DuckDB 单文件、列式压缩、SQL/窗口函数友好，适合本机单用户分析；需要分享时直接导出 Parquet。

**约束**

- 同时只允许一个更新进程；FastAPI 查询持共享文件锁，更新 CLI 持独占文件锁，避免独立 DuckDB 进程同时打开读写连接。
- 更新先写 staging 表并完成质量校验，再在一个事务中合并。
- 不允许前端直接写数据库。
- 行情、股票池与复权因子按 `revision` 追加版本，不覆盖旧版本；查询取指定 revision 之前每个业务主键的最新一行。
- 每次研究必须记录 `data_revision`，不能只记录“最新数据”。

### ADR-002：原始价与复权因子分离

`daily_bars` 保存不复权 OHLC、实际成交股数和成交额。全天原始均价为：

```text
vwap_raw = amount_cny / volume_shares
```

`adjust_factors` 保存日期级复权因子。研究视图计算：

```text
open_qfq = open_raw × factor
high_qfq = high_raw × factor
low_qfq  = low_raw × factor
close_qfq = close_raw × factor
vwap_qfq = vwap_raw × factor
```

这样金额和成交股数保持交易所实际口径，价格比较使用统一前复权口径。`vwap_qfq` 必须落在 `[low_qfq, high_qfq]` 内，否则进入质量问题表，不进入正式研究结果。

### ADR-003：Baostock 历史主源，腾讯/东财负责交叉验证与当前发现

- Baostock：
  - `query_all_stock(date)`：指定日期证券与交易状态。
  - `query_history_k_data_plus`：日线、成交额、成交股数、换手、`tradestatus`、`isST`。
  - `query_adjust_factor`：复权因子。
- 东财 `screener.market_snapshot("A")`：发现当前全市场证券和名称；不得单独作为历史股票池。
- 腾讯前复权 K 线：对每批次抽样核验最近 60 日 OHLC/收益方向；最新收盘报价校验成交额均价。

主源失败时保留上一 `data_revision`，不得把部分批次标为完整成功。单票失败可以隔离，但必须报告覆盖率和失败代码。

## 3. 数据模型

### 3.1 `instruments`

| 字段 | 含义 |
|---|---|
| `symbol` | `sh.600000` / `sz.000001`，主键 |
| `code` | 六位代码 |
| `exchange` | `SH` / `SZ` |
| `board` | `main` |
| `name_current` | 当前名称，仅展示 |
| `list_date` / `delist_date` | 上市/退市日期 |
| `first_seen_revision` / `last_seen_revision` | 数据版本边界 |

### 3.2 `universe_daily`

| 字段 | 含义 |
|---|---|
| `trade_date`, `symbol` | 联合主键 |
| `name_asof` | 当日名称 |
| `is_st` | 当日是否 ST |
| `trade_status` | 正常 / 停牌 |
| `total_mcap_cny` | 当日总市值；缺失保持 null |
| `eligible_mainboard` | 主板且当日可纳入 |
| `exclusion_reason` | ST、停牌、市值不足/缺失、上市不足、退市整理等 |
| `ingest_run_id` | 来源批次 |

### 3.3 `daily_bars`

| 字段 | 含义 |
|---|---|
| `trade_date`, `symbol` | 联合主键 |
| `open_raw`, `high_raw`, `low_raw`, `close_raw`, `preclose_raw` | 不复权价格 |
| `volume_shares` | 成交股数 |
| `amount_cny` | 成交额 |
| `turnover_pct` | 换手率 |
| `trade_status`, `is_st` | 当日状态冗余，便于研究查询 |
| `source`, `ingest_run_id`, `observed_at` | 可追溯信息 |

### 3.4 `adjust_factors`

`trade_date + symbol` 为主键，保存 `qfq_factor`、来源和批次。因分红送转更新导致历史前复权值变化时，只更新因子，不改原始成交数据。

### 3.5 `ingest_runs` 与 `quality_issues`

记录批次状态、计划/实际证券数、计划/实际行数、日期范围、源版本、错误数量、校验结果、完成时间与内容哈希。异常行进入 `quality_issues` 或 `quarantine/`，不能静默丢弃。

### 3.6 `daily_features`、`study_runs` 与 `study_signals`

- `daily_features`：`feature_version + trade_date + symbol` 唯一，保存 `r5/r10/r20`、MA、前五日均量、放量倍数、原始/前复权均价、流动性字段。
- `study_runs`：策略版本、参数 JSON、数据截止日、`data_revision`、代码 commit、股票池口径、创建时间。
- `study_signals`：运行 ID、代码、信号日、特征、退出状态和结果。

原始行情不可被策略参数污染；特征可按版本重算；研究结果必须能回到原始批次。

## 4. 增量更新流程

### 初次回填

1. 用 50 只校验集做源验证：普通股、发生过分红、曾 ST、停牌、新股、退市股各有样本。
2. 回填当前市值不低于 30 亿元的主板非 ST 股票：3 个自然月分析窗口 + 30 个交易日预热，预计约 24 万行，先验证页面与查询性能。
3. 扩展到最近五年，并通过历史 `isST`/上市退市信息重建时点股票池，预计约 390 万行。
4. 对最近 60 日按证券抽样 1% 与腾讯前复权行情交叉检查。

### 每日更新

1. 北京时间 16:30 后显式执行更新命令。
2. 确认交易日；获取当日证券池快照。
3. 仅请求每只证券 `max(trade_date) + 1` 之后的数据。
4. 写 staging 表。
5. 执行唯一性、日期、OHLC、金额、均价区间、ST/停牌、覆盖率校验。
6. 事务提交并生成递增 `data_revision`。
7. 生成更新 manifest；失败时上一 revision 仍可查询。
8. 每周导出最近完整 revision 的分区 Parquet。

首版不把更新线程挂进 Uvicorn。先使用明确 CLI，稳定后再接 macOS `launchd` 或 Cursor Automation，避免服务重载造成重复任务。

## 5. 查询与页面

### CLI

```bash
backend/.venv/bin/python tools/market_data.py init
backend/.venv/bin/python tools/market_data.py backfill --market mainboard --months 3 --warmup-days 30 --min-mcap 3000000000
backend/.venv/bin/python tools/market_data.py update
backend/.venv/bin/python tools/market_data.py verify --revision latest
backend/.venv/bin/python tools/market_data.py status
backend/.venv/bin/python tools/market_data.py export --revision latest --format parquet
```

### API

- `GET /api/market-store/status`
- `GET /api/market-store/universe?date=YYYY-MM-DD&board=main&exclude_st=true`
- `GET /api/market-store/bars?codes=...&start=...&end=...&adjust=qfq`
- `POST /api/trend-study/run`：只接收策略参数和数据 revision；服务端执行全市场计算。
- `GET /api/trend-study/runs/{id}`

全市场数据不再由前端加载。前端只接收分页后的候选、聚合统计和单票明细；当前 `frontend/public/trend-lab-data.json` 在过渡期保留为 15 股演示回退，迁移完成后移除。

## 6. 文件级实施计划

### Task 1：数据库与目录契约

**Files**

- Create: `backend/market_store.py`
- Create: `backend/tests/test_market_store.py`
- Modify: `backend/requirements.txt`

**Steps**

1. 先写临时数据根、schema 初始化、重复初始化、单写者锁测试。
2. 引入 `duckdb`，创建核心表与 schema version。
3. 实现 staging → validate → transaction merge。
4. 测试失败批次不改变 active revision。
5. Commit: `feat(data): 建立可版本化主板行情库`

### Task 2：主板时点股票池

**Files**

- Create: `backend/market_universe.py`
- Create: `backend/tests/test_market_universe.py`

**Steps**

1. 测试沪深主板代码分类。
2. 测试当日 ST、停牌、退市整理、市值不足和市值缺失排除。
3. 测试 3 个月 MVP 明确标记当前快照市值日期，不伪装成历史时点市值。
4. 测试历史日期不使用当前名称或当前市值判断资格。
5. 测试后来退市证券仍存在于历史股票池。
5. Commit: `feat(data): 建立主板非ST时点股票池`

### Task 3：Baostock 历史采集与复权

**Files**

- Create: `backend/market_ingest.py`
- Create: `backend/tests/test_market_ingest.py`
- Modify: `backend/requirements.txt`

**Steps**

1. 用伪造 Baostock 结果测试字段解析、空值、错误码和断点续传。
2. 保存不复权 OHLC、成交额、成交股数、状态与复权因子。
3. 测试 `vwap_raw` 与 `vwap_qfq` 计算。
4. 测试均价越界进入 quarantine。
5. 添加腾讯抽样交叉验证。
6. Commit: `feat(data): 接入主板历史日线与复权因子`

### Task 4：管理 CLI

**Files**

- Create: `tools/market_data.py`
- Create: `backend/tests/test_market_data_cli.py`

**Steps**

1. 实现 `init/backfill/update/verify/status/export`。
2. 添加进度、覆盖率、预计剩余时间和可恢复 checkpoint。
3. 测试重复 update 幂等。
4. 测试中断后继续只补缺失日期。
5. Commit: `feat(tools): 添加主板行情库管理命令`

### Task 5：特征与研究运行版本

**Files**

- Create: `backend/trend_study.py`
- Create: `backend/tests/test_trend_study.py`
- Modify: `frontend/src/features/workbench/trendEngine.ts`

**Steps**

1. 将趋势特征与退出模拟迁移为服务端纯函数。
2. 测试只使用信号日可见信息。
3. 测试时点非 ST 股票池、停牌、涨跌停不可成交和 T+1。
4. 保存 feature/study version 与 data revision。
5. 保留前端引擎用于 15 股演示对照，直到结果逐项一致。
6. Commit: `feat(research): 版本化全主板趋势研究运行`

### Task 6：API 与页面迁移

**Files**

- Modify: `backend/app.py`
- Create: `backend/tests/test_market_store_api.py`
- Modify: `frontend/src/pages/TrendLabPage.tsx`
- Modify: `frontend/src/features/workbench/TrendDateReview.tsx`
- Modify: `frontend/src/lib/api.ts`

**Steps**

1. 加入状态、股票池、运行、结果 API。
2. 页面展示 data revision、覆盖率、股票池数量、失败证券和源更新时间。
3. 全市场计算改为后端任务；前端轮询进度并分页展示。
4. 单票详情按需查询，不把数百万行传给浏览器。
5. 浏览器验证日期切换、筛选、失败提示和历史运行复现。
6. Commit: `feat(ui): 趋势实验室切换主板历史数据层`

### Task 7：备份、CI 与运维

**Files**

- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Create: `docs/adr/001-mainboard-market-data-store.md`

**Steps**

1. CI 使用小型固定 DuckDB fixture，不联网回填。
2. 文档化数据目录、备份、恢复和磁盘估算。
3. 添加每周 Parquet 导出及校验命令。
4. 先人工运行每日更新；确认连续 20 个交易日稳定后再自动化。
5. Commit: `docs: 完善主板行情库运维与架构决策`

## 7. 验收标准

- 当前主板非 ST、总市值不低于 30 亿元且已有有效行情的股票池数量与东财快照差异可解释；基准日为 2,687 只，另有 64 只市值缺失及 1 只尚未上市交易证券被单列。
- 3 个月分析窗口 + 30 个交易日预热的首批回填成功率 ≥ 99%，失败证券有明确清单。
- `(trade_date, symbol)` 无重复；不存在未来日期。
- 正常交易行满足 `low <= open/close/vwap <= high`。
- `amount_cny > 0` 时 `volume_shares > 0`；停牌行不伪造价格和均价。
- 历史查询按信号日 `is_st` 过滤，包含后来退市证券。
- 同参数 + 同 data revision + 同策略版本得到相同结果。
- 中断更新后可继续，重复更新不增加重复行。
- FastAPI 不向浏览器返回全量日线；单次列表响应有分页和上限。
- 后端离线测试、前端测试和生产构建全部通过。

## 8. 容量与性能预估

| 范围 | 约行数 | DuckDB 预估 | 用途 |
|---|---:|---:|---|
| 当前 2,687 只 × 3 个月 + 30 日预热 | 约 24 万 | 20–60 MB | 首期验收 |
| 五年时点主板股票池 | 约 390 万 | 250–600 MB | 正式趋势验证 |
| 十年时点主板股票池 | 约 750–850 万 | 500 MB–1.2 GB | 多周期稳健性研究 |

实际体积取决于字符串字典、索引、特征版本数量和 Parquet 压缩。`study_signals` 不复制整张日线表；旧特征版本可按策略版本清理，但原始行情和 ingest manifest 不删除。
