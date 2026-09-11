# Bruce 投资工作台：本地增量开发计划

更新：2026-09-09。用户已确认采用本地路线，旧版本不保留，不做旧格式兼容。

## 技术与数据边界

沿用 React 19、TypeScript、Vite、Tailwind、FastAPI、本地 JSON。工作台保存当前卡片、证据和计划，覆盖修改与删除均不保留历史；修订计数只用于并发冲突检查，不是历史版本。已有真实持仓、成交与私有台账不删除、不迁移。

数据路径：`VR_DATA_DIR/workbench/current.json`，默认 `~/.vibe-research/workbench/current.json`。首版本机单用户。风险额度计算、手机访问、自动行情筛选不属于 v0.1。

## v0.1：投资卡与当前计划

已实现文件：
- `backend/workbench.py`：当前记录、输入校验、文件锁、原子保存、并发冲突检查、备份恢复 API。
- `backend/app.py`：注册工作台路由，沿用既有 API 鉴权。
- `frontend/src/pages/InvestmentWorkbench.tsx`：卡片列表、搜索/状态筛选、证据表单、计划表单、复查提示、导出恢复、删除与未保存提醒。
- `frontend/src/router.tsx`、`frontend/src/components/layout/Layout.tsx`：投资工作台入口。
- `backend/tests/test_workbench.py`：覆盖修改、冲突、计划校验、服务端时间、备份恢复、损坏文件保护。

使用流程：新建卡片 → 保存草稿 → 填写入场/退出条件与复查日期 → 保存并确认计划。修改已确认内容后回到草稿，重新确认时服务端记录当前时间。未设置风险额度，不显示“允许执行”。不保留历史，因此不能凭当前计划证明过往决策依据。

验收：填写、保存、刷新读取、覆盖修改、证据状态、计划字段校验、失败反馈、导出/恢复。测试使用 `/tmp/bruce-workbench-qa`，与真实数据隔离。

## v0.2：成交与复盘闭环（已实现）

复用 `backend/trade_service.py` 的成交 ID 和记账流程。新模块只关联成交，不重复增减持仓。单账户同证券先限定一个活跃周期；支持无事前计划的真实成交。计划内容不保留历史，关联只能作为当前研究链接，不能做历史逻辑一致性审计。

实现：成交关联、加减仓到清仓周期、单笔复盘、E01–E10 错误标签。先核查现有费用与成本语义；费用缺失只能显示毛收益。真实与模拟使用独立数据目录。

## v0.3：使用反馈驱动

从自选/持仓快速建卡、一种实际券商文件导入、完整周期基础统计。导入先预览，重叠文件去重。优先修复日常录入中的重复劳动。

## 后续

按需要增加主题比较、数据筛选、资金流水及账户对账、风险预算、自动更新、手机访问。只有账务数据齐全后才计算完整账户净值与回撤。

## 验证命令

仓库根目录：

```sh
backend/.venv/bin/python -m pytest backend/tests/test_workbench.py backend/tests/test_trade_service.py backend/tests/test_daily_review_workflow.py -q
```

前端目录：

```sh
npm run build
```

开发分支：`codex/local-investment-workbench`。每阶段提供可用页面、实际交互验收和已知限制；不为未来功能提前搭建复杂基础设施。

实现与验收详见 `docs/plans/2026-09-09-workbench-journal-v02.md`。
