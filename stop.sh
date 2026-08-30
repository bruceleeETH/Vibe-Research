#!/usr/bin/env bash
# 关闭本机 Vibe-Research 前后端（:5899 前端 / :8900 后端）。
# 可双击 stop.command，或在终端: ./stop.sh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

FRONTEND_PORT=5899
BACKEND_PORT=8900
RUN_DIR="$ROOT/.run"

_kill_port() {
  local port="$1" label="$2"
  local pids
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [ -z "$pids" ]; then
    echo "[stop] $label :$port  未在监听"
    return 0
  fi
  echo "[stop] $label :$port  → 结束 PID: $pids"
  # 先温和再强杀；uvicorn --reload 会留子进程，按端口杀最稳
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 0.4
  pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
}

_kill_port "$BACKEND_PORT" "后端"
_kill_port "$FRONTEND_PORT" "前端"

# 清掉 start.sh 写下的 pid 记录
if [ -d "$RUN_DIR" ]; then
  rm -f "$RUN_DIR"/backend.pid "$RUN_DIR"/frontend.pid "$RUN_DIR"/started_at 2>/dev/null || true
fi

echo
echo "[status] 关闭后端口状态："
./status.sh || true
