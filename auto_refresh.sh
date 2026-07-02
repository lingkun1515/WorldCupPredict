#!/bin/bash
# ═══════════════════════════════════════════════════
# WorldCupPredict — 每小时自动刷新
# 用法: ./auto_refresh.sh
# 后台: nohup ./auto_refresh.sh &
# ═══════════════════════════════════════════════════
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/data/refresh.log"

echo "[$(date)] 自动刷新已启动 (每小时)" | tee -a "$LOG"
echo "  日志: $LOG" | tee -a "$LOG"

while true; do
    sleep 3600
    echo "[$(date)] 刷新中..." | tee -a "$LOG"
    cd "$DIR"
    python3 refresh_data.py >> "$LOG" 2>&1
    echo "[$(date)] 完成" | tee -a "$LOG"
done
