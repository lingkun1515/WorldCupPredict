"""WorldCupPredict — AI-Powered World Cup 2026 Daily Report."""
import asyncio, json, os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from jinja2 import Environment, FileSystemLoader
from fastapi.templating import Jinja2Templates

from config import MATCHES_FILE, DATA_DIR
from shared_data import COUNTRY_FLAGS, load_cn_names
from scraper.models import MatchData
from scraper.betting import _generate_fallback_odds, scrape_betting_odds
from scraper.news import _generate_fallback_news, scrape_news_and_commentary
from analyzer.reporter import build_daily_report, save_report, load_report, list_reports

app = FastAPI(title="WorldCupPredict", version="1.0.0")
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


jinja_env = Environment(loader=FileSystemLoader(str(BASE_DIR / "templates")))

def flag_filter(name): return COUNTRY_FLAGS.get(name, "🏳️")

# Chinese team names
CN_NAMES = load_cn_names()
jinja_env.filters["cn"] = lambda name: CN_NAMES.get(name, name)
jinja_env.filters["flag"] = flag_filter


def load_matches():
    if os.path.exists(MATCHES_FILE):
        with open(MATCHES_FILE, encoding="utf-8") as f: return json.load(f)
    return []


def _build_matches_fallback(matches_raw):
    """Fast path: use fallback generators, no Playwright."""
    ms = []
    for m in matches_raw:
        ms.append(MatchData(
            match_id=m["match_id"], home_team=m["home_team"], away_team=m["away_team"],
            kickoff=m["kickoff"], venue=m["venue"], stage=m["stage"],
            odds=_generate_fallback_odds(m["home_team"], m["away_team"]),
            news=_generate_fallback_news(m["home_team"], m["away_team"], m["stage"]),
        ))
    return ms


async def _build_matches_live(matches_raw):
    """Slow path: real Playwright scraping."""
    ms = []
    for m in matches_raw:
        odds, news = await asyncio.gather(
            scrape_betting_odds(m["home_team"], m["away_team"]),
            scrape_news_and_commentary(m["home_team"], m["away_team"], m["stage"]),
        )
        ms.append(MatchData(
            match_id=m["match_id"], home_team=m["home_team"], away_team=m["away_team"],
            kickoff=m["kickoff"], venue=m["venue"], stage=m["stage"],
            odds=odds, news=news,
        ))
    return ms


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, refresh: bool = Query(default=False)):
    today = datetime.now().strftime("%Y-%m-%d")
    report = load_report(today) if not refresh else None
    if not report:
        import asyncio
        matches = _build_matches_fallback(load_matches())
        try:
            report = await asyncio.wait_for(build_daily_report(matches), timeout=120)
            save_report(report)
        except asyncio.TimeoutError:
            # Fallback: generate with just rules, no LLM
            print("[TIMEOUT] Report generation timed out, using quick fallback")
            from analyzer.reporter import _load_results
            from analyzer.statistical import poisson_prediction
            from datetime import timedelta
            results = _load_results()
            completed = {(r['home'], r['away']) for r in results} | {(r['away'], r['home']) for r in results}
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            predictions = []
            for m in matches:
                key = (m.home_team, m.away_team)
                if key in completed or (m.away_team, m.home_team) in completed:
                    continue
                if m.kickoff[:10] <= yesterday:
                    continue
                p = poisson_prediction(m.home_team, m.away_team)
                p["match_date"] = m.kickoff[:10] if m.kickoff else ""
                predictions.append(p)
            predictions.sort(key=lambda p: p.get("match_date", "9999"))
            report = {
                "date": today,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "match_count": len(matches),
                "predictions": predictions,
                "results": results,
                "accuracy": {"total": 0, "results_available": 0, "matched_predictions": 0,
                    "correct_outcomes": 0, "exact_scores": 0, "outcome_rate": "—", "score_rate": "—"},
            }
    template = jinja_env.get_template("index.html")
    html = template.render(report=report, now=datetime.now())
    response = HTMLResponse(html)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.get("/archive", response_class=HTMLResponse)
async def archive(request: Request):
    dates = list_reports()
    previews = []
    for d in dates[:30]:
        r = load_report(d)
        if r:
            previews.append({
                "date": d,
                "predictions": len(r.get("predictions", [])),
                "results": len(r.get("results", [])),
                "accuracy": r.get("accuracy", {}),
            })
    template = jinja_env.get_template("archive.html")
    html = template.render(dates=list(zip(dates, previews)))
    response = HTMLResponse(html)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.get("/export", response_class=HTMLResponse)
async def export_report(request: Request):
    """Export today's report as a standalone static HTML file."""
    today = datetime.now().strftime("%Y-%m-%d")
    report = load_report(today)
    if not report:
        matches = _build_matches_fallback(load_matches())
        report = await build_daily_report(matches)
        save_report(report)
    template = jinja_env.get_template("export.html")
    html = template.render(report=report)
    os.makedirs("_site", exist_ok=True)
    with open(f"_site/report_{today}.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open("_site/latest.html", "w", encoding="utf-8") as f:
        f.write(html)
    return HTMLResponse(html)


@app.get("/report/{date_str}", response_class=HTMLResponse)
async def view_report(request: Request, date_str: str):
    report = load_report(date_str)
    if not report:
        return HTMLResponse("<h1>报告未找到</h1><p><a href='/'>返回首页</a></p>", status_code=404)
    template = jinja_env.get_template("index.html")
    html = template.render(report=report, now=datetime.now())
    return HTMLResponse(html)


@app.get("/api/report/{date_str}")
async def api_report(date_str: str):
    r = load_report(date_str)
    return r if r else {"error": "not found", "date": date_str}


@app.get("/api/today")
async def api_today():
    today = datetime.now().strftime("%Y-%m-%d")
    r = load_report(today)
    return r if r else {"error": "no report yet", "date": today}


@app.get("/api/dates")
async def api_dates():
    return {"dates": list_reports()}


@app.get("/api/live-scrape")
async def api_live_scrape():
    """Fetch latest results from ESPN API + Wikipedia, rebuild if new data found."""
    from scraper.live_fetcher import live_refresh_results
    import asyncio as _asyncio
    new, updated, total = await _asyncio.to_thread(live_refresh_results)
    if new > 0 or updated > 0:
        matches = _build_matches_fallback(load_matches())
        report = await _asyncio.wait_for(build_daily_report(matches), timeout=120)
        save_report(report)
        return {"status": "refreshed", "new_results": new, "updated": updated, "total_results": total, "predictions": len(report.get("predictions", []))}
    return {"status": "up_to_date", "total_results": total, "new_results": 0, "updated": 0}



@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return "User-agent: *\nAllow: /\nDisallow: /api/\n"


@app.get("/sitemap.xml")
async def sitemap():
    dates = list_reports()
    urls = ["<url><loc>/</loc></url>", "<url><loc>/archive</loc></url>"]
    for d in dates[:90]:
        urls.append(f"<url><loc>/report/{d}</loc></url>")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>"
    return PlainTextResponse(xml, media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
