#!/usr/bin/env bash
# Vibe-Research 一键启动：后端(:8900) + 前端(:5899)，Ctrl+C 同时退出。
# 首次运行会自动创建虚拟环境 / 安装依赖。
set -e
cd "$(dirname "$0")"

# 后端依赖（首次自动装）
if [ ! -x backend/.venv/bin/python ]; then
  echo "[setup] 创建后端虚拟环境并安装依赖（首次约 1-2 分钟）…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -r backend/requirements.txt
fi

# 前端依赖（首次自动装）
if [ ! -d frontend/node_modules ]; then
  echo "[setup] 安装前端依赖…"
  (cd frontend && npm install)
fi

# 8900 被旧后端占着就先清掉
lsof -ti :8900 | xargs kill 2>/dev/null || true

echo "[start] 后端 → http://127.0.0.1:8900 （--reload 热更新）"
(cd backend && .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8900 --reload) &
BACK_PID=$!
trap 'echo; echo "[stop] 关闭后端…"; kill $BACK_PID 2>/dev/null' EXIT

# 稍等后自动打开浏览器（macOS）
( sleep 3; open "http://localhost:5899/review-pool" 2>/dev/null || true ) &

echo "[start] 前端 → http://localhost:5899 （Ctrl+C 同时退出前后端）"
cd frontend && npm run dev
