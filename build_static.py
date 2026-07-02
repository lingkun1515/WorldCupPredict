#!/usr/bin/env python3
"""Generate static HTML site from reporter. Run this to refresh predictions."""
import asyncio, json, os, sys, shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from analyzer.reporter import build_daily_report, _load_results, save_report, load_report, list_reports
from scraper.betting import _generate_fallback_odds
from scraper.news import _generate_fallback_news
from scraper.models import MatchData
from shared_data import COUNTRY_FLAGS, load_cn_names
from jinja2 import Environment, FileSystemLoader

jinja_env = Environment(loader=FileSystemLoader(str(BASE_DIR / 'templates')))

CN_NAMES = load_cn_names(BASE_DIR / "data")
jinja_env.filters["cn"] = lambda name: CN_NAMES.get(name, name)
jinja_env.filters["flag"] = lambda name: COUNTRY_FLAGS.get(name, "🏳️")

def inline_css():
    css_path = BASE_DIR / 'static' / 'css' / 'style.css'
    if not css_path.exists():
        return
    css = css_path.read_text()
    site = BASE_DIR / '_site'
    for fname in ['index.html', 'latest.html']:
        fp = site / fname
        if fp.exists():
            h = fp.read_text()
            h = h.replace('<link rel="stylesheet" href="./static/css/style.css">',
                          f'<style>\n{css}\n</style>')
            h = h.replace('<link rel="stylesheet" href="/static/css/style.css">',
                          f'<style>\n{css}\n</style>')
            fp.write_text(h)

def main():
    print(f"[{datetime.now()}] Building static site...")
    with open(BASE_DIR / 'data' / 'matches.json', encoding="utf-8") as f:
        all_matches = json.load(f)
    results = _load_results()
    done = {(r["home"],r["away"]) for r in results} | {(r["away"],r["home"]) for r in results}
    pending = [m for m in all_matches if (m["home_team"],m["away_team"]) not in done]
    matches = []
    for m in pending:
        odds = _generate_fallback_odds(m['home_team'], m['away_team'])
        news = _generate_fallback_news(m['home_team'], m['away_team'], m['stage'])
        matches.append(MatchData(match_id=m['match_id'], home_team=m['home_team'],
            away_team=m['away_team'], kickoff=m['kickoff'], venue=m['venue'],
            stage=m['stage'], odds=odds, news=news))
    report = asyncio.run(build_daily_report(matches))
    report["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_report(report)
    template = jinja_env.get_template("index.html")
    # Group predictions by day for template
    day_groups = {}
    for p in report['predictions']:
        d = p.get('match_date', '未知')
        if d not in day_groups:
            day_groups[d] = []
        day_groups[d].append(p)
    report['day_groups'] = day_groups
    html = template.render(report=report, now=datetime.now())
    site = BASE_DIR / '_site'
    site.mkdir(exist_ok=True)
    (site / 'static' / 'css').mkdir(parents=True, exist_ok=True)
    (site / 'index.html').write_text(html)
# CSS now inlined — no need to copy
    dates = list_reports()
    previews = {}
    for d in dates[:30]:
        r = load_report(d)
        if r:
            previews[d] = {"predictions": len(r.get("predictions",[])),
                          "results": len(r.get("results",[])),
                          "accuracy": r.get("accuracy",{})}
    date_pairs = [(d, previews.get(d)) for d in dates]
    archive_template = jinja_env.get_template("archive.html")
    archive_html = archive_template.render(dates=date_pairs)
    (site / 'archive.html').write_text(archive_html)
    export_template = jinja_env.get_template("export.html")
    export_html = export_template.render(report=report)
    (site / 'latest.html').write_text(export_html)
    today = datetime.now().strftime("%Y-%m-%d")
    (site / f'report_{today}.html').write_text(export_html)
    inline_css()
    _minify_site()
    print(f"  index: {len(html):,}B  archive: {len(archive_html):,}B  export: {len(export_html):,}B")
    print("Done.")


def _minify_site():
    """Simple whitespace minification for production HTML."""
    import re
    site = BASE_DIR / '_site'
    for fname in site.iterdir():
        if fname.suffix == '.html' and fname.is_file():
            html = fname.read_text(encoding='utf-8')
            # Collapse whitespace between tags
            html = re.sub(r'>\s+<', '><', html)
            fname.write_text(html, encoding='utf-8')

def _minify_site():
    """Simple whitespace minification for production HTML."""
    import re
    site = BASE_DIR / '_site'
    for fname in site.iterdir():
        if fname.suffix == '.html' and fname.is_file():
            html = fname.read_text(encoding='utf-8')
            # Collapse whitespace between tags
            html = re.sub(r'>\s+<', '><', html)
            fname.write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
