#!/bin/bash
# ═══════════════════════════════════════════════════
# WorldCupPredict — 一键启动(含自动刷新)
# 浏览器: http://localhost:8080
# 按 Ctrl+C 停止所有服务
# ═══════════════════════════════════════════════════
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8080
LOG="$DIR/data/auto.log"

cd "$DIR"

# 清理
kill $(lsof -ti :$PORT) 2>/dev/null
sleep 0.5

echo "🏆 WorldCupPredict"
echo ""

# 步骤1: 构建
echo "[1/3] 生成预测..."
python3 build_static.py 2>/dev/null
echo ""

# 步骤2: 启动HTTP服务器(后台)
cd "$DIR/_site"
python3 -m http.server $PORT --bind 0.0.0.0 &
SERVER_PID=$!
echo "[2/3] 服务器已启动: http://localhost:$PORT (PID $SERVER_PID)"

# 步骤3: 启动自动刷新(后台，每小时)
cd "$DIR"
(
  while true; do
    sleep 3600
    echo "[$(date +%H:%M)] 自动刷新中..." >> "$LOG"
    python3 refresh_data.py >> "$LOG" 2>&1
    echo "[$(date +%H:%M)] 完成" >> "$LOG"
  done
) &
REFRESH_PID=$!
echo "[3/3] 自动刷新已启动 (每小时, PID $REFRESH_PID)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🌐 http://localhost:$PORT"
echo "  📋 自动每小时抓取Wikipedia赛果"
echo "  ⌨️  按 Ctrl+C 停止"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Ctrl+C 清理
trap "kill $SERVER_PID $REFRESH_PID 2>/dev/null; echo ' 已停止'; exit 0" INT TERM

# 保持前台
wait
