#!/usr/bin/env bash
# 查看 Vibe-Research 前后端是否在跑（:5899 / :8900）。
# 用法: ./status.sh
cd "$(dirname "$0")"

FRONTEND_PORT=5899
BACKEND_PORT=8900

_port_line() {
  local port="$1" label="$2"
  local listen health=""
  listen=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $1,$2}' | head -3)
  if [ -z "$listen" ]; then
    printf "  %-8s :%-5s  %s\n" "$label" "$port" "○ 未运行"
    return 1
  fi
  # 简短健康探测
  if [ "$port" = "$BACKEND_PORT" ]; then
    code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 1 "http://127.0.0.1:${port}/api/health" 2>/dev/null || echo "000")
    health="  health=$code"
  elif [ "$port" = "$FRONTEND_PORT" ]; then
    code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 1 "http://127.0.0.1:${port}/" 2>/dev/null || echo "000")
    health="  http=$code"
  fi
  printf "  %-8s :%-5s  %s%s\n" "$label" "$port" "● 在跑  ($listen)" "$health"
  return 0
}

echo "Vibe-Research 服务状态  ($(date '+%H:%M:%S'))"
echo "────────────────────────────────────"
be=0; fe=0
_port_line "$BACKEND_PORT" "后端" && be=1 || true
_port_line "$FRONTEND_PORT" "前端" && fe=1 || true
echo "────────────────────────────────────"

if [ -f .run/started_at ]; then
  echo "  start.sh 记录启动于: $(cat .run/started_at)"
fi

if [ "$be" = 1 ] && [ "$fe" = 1 ]; then
  echo "  打开: http://127.0.0.1:${FRONTEND_PORT}/"
  echo "  关闭: ./stop.sh"
  exit 0
elif [ "$be" = 0 ] && [ "$fe" = 0 ]; then
  echo "  均未运行。启动: ./start.sh"
  exit 1
else
  echo "  ⚠ 只起了一半（关干净: ./stop.sh ，再 ./start.sh）"
  exit 2
fi
