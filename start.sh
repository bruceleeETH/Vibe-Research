#!/usr/bin/env bash
# Vibe-Research 一键启动：后端(:8900) + 前端(:5899)，Ctrl+C 同时退出。
# 首次运行会自动创建虚拟环境 / 安装依赖。
#
# 配套:
#   ./status.sh   看是否还在跑（别靠「关终端」猜）
#   ./stop.sh     强制关掉占用 5899/8900 的进程
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

FRONTEND_PORT=5899
BACKEND_PORT=8900
# 必须用绝对路径：后面会 cd frontend，相对 .run 会写到 frontend/.run 导致失败
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"

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

# 启动前清掉旧实例（避免「以为关了其实还在」+ 端口冲突）
echo "[start] 清理旧进程（若有）…"
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  释放 :$port  PID $pids"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.3
    pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    # shellcheck disable=SC2086
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  fi
done

_cleanup() {
  echo
  echo "[stop] Ctrl+C / 退出 → 关闭前后端…"
  # 优先按端口杀：覆盖 uvicorn --reload 子进程、vite 等
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    # shellcheck disable=SC2086
    [ -n "$pids" ] && kill $pids 2>/dev/null || true
  done
  [ -n "${BACK_PID:-}" ] && kill "$BACK_PID" 2>/dev/null || true
  [ -n "${FRONT_PID:-}" ] && kill "$FRONT_PID" 2>/dev/null || true
  sleep 0.3
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    # shellcheck disable=SC2086
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  done
  rm -f "$RUN_DIR"/backend.pid "$RUN_DIR"/frontend.pid "$RUN_DIR"/started_at 2>/dev/null || true
  echo "[stop] 完成。确认: ./status.sh"
}
trap _cleanup EXIT INT TERM

date '+%Y-%m-%d %H:%M:%S' > "$RUN_DIR/started_at"

echo "[start] 后端 → http://127.0.0.1:${BACKEND_PORT} （--reload 热更新）"
(
  cd backend
  exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload
) &
BACK_PID=$!
echo "$BACK_PID" > "$RUN_DIR/backend.pid"

# 稍等后自动打开浏览器（macOS）
( sleep 3; open "http://127.0.0.1:${FRONTEND_PORT}/intel" 2>/dev/null || true ) &

echo "[start] 前端 → http://127.0.0.1:${FRONTEND_PORT} （Ctrl+C 同时退出前后端）"
echo "[tip]  另开终端可查状态: ./status.sh   强制全关: ./stop.sh"
(
  cd "$ROOT/frontend"
  exec npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
) &
FRONT_PID=$!
echo "$FRONT_PID" > "$RUN_DIR/frontend.pid"

# 以前端为主进程：等它退出（Ctrl+C 会触发 trap）
wait "$FRONT_PID"
