#!/usr/bin/env python3
"""
WorldCupPredict 持续优化调度器
功能: 守护服务器、定时刷新预测、抓取Wikipedia赛果、追踪准确率、自动调整模型
用法: python3 scheduler.py [--daemon]
"""
import asyncio, json, os, sys, time, signal, subprocess, traceback, re
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SITE_DIR = BASE_DIR / "_site"
LOG_FILE = Path("/tmp/wcp_scheduler.log")
ACCURACY_HISTORY_FILE = DATA_DIR / "accuracy_history.json"
SERVER_PORT = 8080
CHECK_INTERVAL = 30
REFRESH_INTERVAL = 21600
RUNNING = True

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def ensure_server():
    import urllib.request
    try:
        urllib.request.Request(f"http://127.0.0.1:{SERVER_PORT}/health")
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{SERVER_PORT}/health"), timeout=5)
        return True
    except Exception:
        pass
    log("Server down — restarting...")
    subprocess.run(f"kill $(lsof -ti :{SERVER_PORT})", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(1)
    lf = open(LOG_FILE, "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app",
         "--host", "0.0.0.0", "--port", str(SERVER_PORT),
         "--log-level", "warning"],
        cwd=str(BASE_DIR), stdout=lf, stderr=lf)
    time.sleep(3)
    return ensure_server()

async def refresh_predictions():
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"http://127.0.0.1:{SERVER_PORT}/?refresh=true",
                             timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    log("Predictions refreshed OK")
                    return True
    except Exception as e:
        log(f"Refresh failed: {e}")
    return False

async def try_scrape_wikipedia():
    """Try multiple sources: ESPN API first, then Wikipedia as fallback."""
    from scraper.live_fetcher import live_refresh_results
    new, updated, total = live_refresh_results()
    if new > 0 or updated > 0:
        log(f"Live fetch: {new} new, {updated} updated, {total} total results")
        await refresh_predictions()
        export_static()
        return

    import aiohttp
    matches_file = DATA_DIR / "matches.json"
    results_file = DATA_DIR / "results.json"
    if not matches_file.exists():
        return
    with open(matches_file, encoding="utf-8") as f:
        matches = json.load(f)
    results = []
    if results_file.exists():
        with open(results_file, encoding="utf-8") as f:
            results = json.load(f)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    completed_set = {(r["home"], r["away"]) for r in results} | {(r["away"], r["home"]) for r in results}
    pending = [m for m in matches
               if m.get("kickoff", "")[:10] <= yesterday
               and not m.get("completed")
               and (m["home_team"], m["away_team"]) not in completed_set]
    if not pending:
        return
    log(f"Wiki: {len(pending)} pending — {[m['home_team']+'/'+m['away_team'] for m in pending]}")
    wiki_url = ("https://en.wikipedia.org/w/api.php?action=parse"
                "&page=2026_FIFA_World_Cup_knockout_stage&prop=text&format=json&origin=*")
    try:
        async with aiohttp.ClientSession() as s:
            for proxy in [None, "http://127.0.0.1:7897"]:
                try:
                    kw = {"timeout": aiohttp.ClientTimeout(total=15)}
                    if proxy:
                        kw["proxy"] = proxy
                    async with s.get(wiki_url, **kw) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            text = data.get("parse",{}).get("text",{}).get("*","")
                            if text:
                                log(f"Wiki fetched ({len(text)} chars)")
                                _parse_wiki(text, pending, results)
                                return
                except Exception:
                    continue
    except Exception as e:
        log(f"Wiki scrape error: {e}")

def _parse_wiki(html, pending, results):
    found = 0
    for m in pending:
        home, away = m["home_team"], m["away_team"]
        pat = re.compile(re.escape(home) + r'.*?(\d+)\s*[–\-—]\s*(\d+).*?' + re.escape(away), re.I | re.DOTALL)
        mg = pat.search(html)
        if mg:
            hg, ag = int(mg.group(1)), int(mg.group(2))
            r = {"home":home,"away":away,"home_goals":hg,"away_goals":ag,
                 "stage":m.get("stage","淘汰赛"),"date":m.get("kickoff","")[:10],"venue":m.get("venue","")}
            pm = re.search(r'\((\d+)\s*[–\-—]\s*(\d+)\s*(?:p|pen)', html[mg.start():mg.start()+500], re.I)
            if pm:
                r["penalties"] = f"{pm.group(1)}-{pm.group(2)}"
                r["winner"] = home if int(pm.group(1)) > int(pm.group(2)) else away
            results.append(r)
            log(f"  OK: {home} {hg}-{ag} {away}")
            found += 1
            # Update matches.json
            mf = DATA_DIR / "matches.json"
            with open(mf, encoding="utf-8") as f:
                am = json.load(f)
            for x in am:
                if x["home_team"]==home and x["away_team"]==away:
                    x["completed"]=True
                    x["home_goals"]=hg
                    x["away_goals"]=ag
                    if pm:
                        x["home_penalties"]=int(pm.group(1))
                        x["away_penalties"]=int(pm.group(2))
                    break
            with open(mf, "w", encoding="utf-8") as f:
                json.dump(am,f,indent=2,ensure_ascii=False)
    if found:
        rf = DATA_DIR / "results.json"
        with open(rf, "w", encoding="utf-8") as f:
            json.dump(results,f,indent=2,ensure_ascii=False)
        log(f"Saved {found} new results")

def check_data_anomalies():
    fixes = 0
    rf = DATA_DIR / "team_ratings.json"
    if rf.exists():
        with open(rf, encoding="utf-8") as f:
            ratings = json.load(f)
        garbage = ["June","Congo","El Aynaoui","Tah","Maur","Bosnia","Herzegovina",
                   "Cura","Czech Republic","Haiti","Iraq","Jordan","Uzbekistan","Scotland"]
        for k in garbage:
            if k in ratings:
                del ratings[k]
                log(f"  Removed: {k}")
                fixes += 1
        mf = DATA_DIR / "matches.json"
        if mf.exists():
            with open(mf, encoding="utf-8") as f:
                ms = json.load(f)
            for m in ms:
                for t in [m["home_team"],m["away_team"]]:
                    if t not in ratings:
                        ratings[t] = 70
                        log(f"  Added rating: {t}=70")
                        fixes += 1
        if fixes:
            with open(rf, "w", encoding="utf-8") as f:
                json.dump(ratings,f,indent=2,ensure_ascii=False)
    return fixes

def update_accuracy():
    rf, pf = DATA_DIR / "results.json", DATA_DIR / "predictions.json"
    if not rf.exists() or not pf.exists():
        return
    with open(rf, encoding="utf-8") as f:
        results = json.load(f)
    with open(pf, encoding="utf-8") as f:
        preds = json.load(f)
    history = []
    if ACCURACY_HISTORY_FILE.exists():
        with open(ACCURACY_HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
    correct = matched = 0
    for p in preds:
        for r in results:
            if ((p["home_team"]==r["home"] and p["away_team"]==r["away"]) or
                (p["home_team"]==r["away"] and p["away_team"]==r["home"])):
                matched += 1
                pw = p["predicted_home_goals"] > p["predicted_away_goals"]
                aw = r["home_goals"] > r["away_goals"]
                if p["home_team"] == r["away"]:
                    aw = r["away_goals"] > r["home_goals"]
                pd = p["predicted_home_goals"] == p["predicted_away_goals"]
                ad = r["home_goals"] == r["away_goals"]
                if (pw and aw) or (not pw and not aw and not pd) or (pd and ad):
                    correct += 1
    entry = {"date":datetime.now().strftime("%Y-%m-%d %H:%M"),
             "matched":matched,"correct_outcomes":correct,
             "rate":f"{correct}/{matched}" if matched else "n/a"}
    history.append(entry)
    if len(history) > 90:
        history = history[-90:]
    with open(ACCURACY_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history,f,indent=2,ensure_ascii=False)
    if matched:
        log(f"Accuracy: {correct}/{matched}")

def export_static():
    import urllib.request
    try:
        url = f"http://127.0.0.1:{SERVER_PORT}/export"
        resp = urllib.request.urlopen(urllib.request.Request(url), timeout=30)
        html = resp.read().decode()
        SITE_DIR.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        with open(SITE_DIR / f"report_{today}.html", "w", encoding="utf-8") as f:
            f.write(html)
        with open(SITE_DIR / "latest.html", "w", encoding="utf-8") as f:
            f.write(html)
        log(f"Exported ({len(html)} bytes)")
    except Exception as e:
        log(f"Export error: {e}")

async def optimize_weights():
    if not ACCURACY_HISTORY_FILE.exists():
        return
    with open(ACCURACY_HISTORY_FILE, encoding="utf-8") as f:
        history = json.load(f)
    if len(history) < 4:
        return
    rates = []
    for h in history[-4:]:
        if h["matched"] > 0:
            c, t = h["rate"].split("/")
            if t != "n/a" and int(t) > 0:
                rates.append(int(c)/int(t))
    if not rates:
        return
    avg = sum(rates)/len(rates)
    log(f"Model accuracy: {avg:.1%}")
    of = DATA_DIR / "optimization.json"
    os = {}
    if of.exists():
        with open(of, encoding="utf-8") as f:
            os = json.load(f)
    os["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    os["recent_accuracy"] = round(avg,3)
    os["check_count"] = os.get("check_count",0) + 1
    with open(of, "w", encoding="utf-8") as f:
        json.dump(os,f,indent=2,ensure_ascii=False)

async def main_loop():
    global RUNNING
    log("==== Scheduler started ====")
    log(f"PID={os.getpid()}")
    last_refresh = last_export = last_acc = last_wiki = last_anom = 0
    while RUNNING:
        try:
            now = time.time()
            ensure_server()
            if now - last_anom > 1800:
                f = check_data_anomalies()
                if f:
                    log(f"Anomalies fixed: {f}")
                    await refresh_predictions()
                last_anom = now
            if now - last_wiki > 7200:
                await try_scrape_wikipedia()
                last_wiki = now
            if now - last_refresh > REFRESH_INTERVAL:
                log("Scheduled refresh...")
                await refresh_predictions()
                last_refresh = now
            if now - last_acc > 3600:
                update_accuracy()
                await optimize_weights()
                last_acc = now
            h = datetime.now().hour
            if now - last_export > 3600 and h in (6,18):
                export_static()
                last_export = now
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            log(f"Loop error: {e}")
            traceback.print_exc()
            await asyncio.sleep(CHECK_INTERVAL)

def handle_signal(sig, frame):
    global RUNNING
    log(f"Signal {sig}, stopping...")
    RUNNING = False

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    if "--daemon" in sys.argv:
        pid = os.fork()
        if pid > 0:
            print(f"Daemon PID={pid}")
            sys.exit(0)
        os.setsid()
        pid2 = os.fork()
        if pid2 > 0:
            sys.exit(0)
        sys.stdout = open(LOG_FILE, "a", encoding="utf-8")
        sys.stderr = sys.stdout
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        log("Stopped")
    except Exception as e:
        log(f"Fatal: {e}")
        traceback.print_exc()
