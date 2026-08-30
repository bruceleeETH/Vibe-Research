#!/usr/bin/env bash
# macOS 双击关闭前后端
cd "$(dirname "$0")"
./stop.sh
echo
echo "按回车关闭窗口…"
read -r _
