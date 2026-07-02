#!/bin/bash
# WorldCupPredict Watchdog — keeps server alive, refreshes daily
DIR=/home/lenovo/Projects/Temp/WorldCupPredict
PORT=8080
LOG=/tmp/wcp_watchdog.log

echo "[$(date)] Watchdog started (PID $$)" | tee -a $LOG

while true; do
    if ! curl -s --max-time 5 "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
        echo "[$(date)] Server DOWN — restarting..." | tee -a $LOG
        kill $(lsof -ti :$PORT) 2>/dev/null
        sleep 1
        cd $DIR
        # Force regenerate by clearing old cache
        rm -f data/archive/report_$(date +%Y-%m-%d -d '1 day ago').json 2>/dev/null
        nohup python3 -m uvicorn app:app --host 0.0.0.0 --port $PORT --log-level warning >> $LOG 2>&1 &
        sleep 4
        # Verify it started
        if curl -s --max-time 5 "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
            echo "[$(date)] Server restarted OK" | tee -a $LOG
        else
            echo "[$(date)] Server FAILED to start" | tee -a $LOG
        fi
    fi
    sleep 30
done
