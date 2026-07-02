#!/bin/bash
# 持久化守护进程 — 自动启动、自动恢复
DIR=/home/lenovo/Projects/Temp/WorldCupPredict
PORT=8080
LOG=/tmp/wcp_daemon.log

cd $DIR
while true; do
  if ! curl -s --max-time 3 http://127.0.0.1:$PORT/ > /dev/null 2>&1; then
    echo "[$(date)] Server down, restarting..." >> $LOG
    pkill -f "uvicorn app:app" 2>/dev/null
    sleep 1
    nohup python3 -m uvicorn app:app --host 0.0.0.0 --port $PORT >> $LOG 2>&1 &
    sleep 3
    echo "[$(date)] Restarted (PID $!)" >> $LOG
  fi
  sleep 10
done
