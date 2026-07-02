#!/bin/bash
# ═══════════════════════════════════════════════════
# WorldCupPredict — 一键启动完整流水线
# 用法: ./run.sh [--rebuild]
# ═══════════════════════════════════════════════════
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8080
LOG=/tmp/wcp_run.log

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

log "===== WorldCupPredict ====="

# Kill any existing server
if lsof -ti :$PORT > /dev/null 2>&1; then
    log "Killing existing server on :$PORT..."
    kill $(lsof -ti :$PORT) 2>/dev/null || true
    sleep 1
fi

# Step 1: Build static site
if [ "$1" = "--rebuild" ] || [ ! -f "$DIR/_site/index.html" ]; then
    log "Building static site..."
    cd "$DIR"
    python3 build_static.py >> "$LOG" 2>&1
    log "Build: $(wc -c < _site/index.html) bytes, $(grep -c match-card-header _site/index.html) cards"
fi

# Step 2: Start server
cd "$DIR/_site"
log "Starting server on http://0.0.0.0:$PORT ..."
exec python3 -m http.server $PORT --bind 0.0.0.0 2>&1 | while read line; do
    echo "[$(date '+%H:%M:%S')] $line" >> "$LOG"
done
