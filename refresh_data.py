#!/usr/bin/env python3
"""
refresh_data.py — 从 Wikipedia 抓取最新赛果并刷新预测
由 auto_refresh.sh 每小时调用，也可手动运行
用法: python3 refresh_data.py
"""
import json, re, os, ssl, sys, subprocess, urllib.request, signal
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'

# Team name mapping: our names → Wikipedia-compatible variants
TEAM_NAME_ALIASES = {
    "Ivory Coast": ["Ivory Coast", "Côte d'Ivoire", "Cote d'Ivoire"],
    "South Korea": ["South Korea", "Korea Republic"],
    "United States": ["United States", "USA"],
    "Bosnia and Herzegovina": ["Bosnia and Herzegovina", "Bosnia"],
    "DR Congo": ["DR Congo", "Democratic Republic of the Congo", "Congo DR"],
    "Cape Verde": ["Cape Verde", "Cabo Verde"],
    "UAE": ["UAE", "United Arab Emirates"],
}


class TimeoutError(Exception):
    pass


def _handler(signum, frame):
    raise TimeoutError()


def fetch_page(url, label):
    """Fetch a single Wikipedia page."""
    print(f"  Fetching: {label}", flush=True)
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'WorldCupPredict/2026'})
    resp = urllib.request.urlopen(req, timeout=15, context=ctx)
    data = json.loads(resp.read().decode())
    text = data.get('parse', {}).get('text', {}).get('*', '')
    print(f"    Got {len(text):,} chars", flush=True)
    return text


def search_one_match(text, home, away, m):
    """Search for one match result in text. Returns dict or None."""
    home_names = TEAM_NAME_ALIASES.get(home, [home])
    away_names = TEAM_NAME_ALIASES.get(away, [away])

    for hn in home_names:
        for an in away_names:
            # Only search within a reasonable window — 10KB around either team name
            # to avoid catastrophic backtracking in large pages
            idx_h = text.find(hn)
            if idx_h == -1:
                continue
            chunk = text[max(0, idx_h - 2000):min(len(text), idx_h + 8000)]

            pat = re.compile(
                re.escape(hn) + r'[^<]{0,500}?(\d{1,2})\s*[–\-—]\s*(\d{1,2})[^>]{0,500}?' + re.escape(an),
                re.I | re.DOTALL
            )
            mg = pat.search(chunk)
            if mg:
                hg, ag = int(mg.group(1)), int(mg.group(2))
                if hg <= 15 and ag <= 15:
                    r = {
                        "home": home, "away": away,
                        "home_goals": hg, "away_goals": ag,
                        "date": m.get('kickoff', '')[:10],
                        "stage": m.get('stage', '淘汰赛'),
                        "venue": m.get('venue', ''),
                    }
                    # Check for penalties
                    pm = re.search(
                        r'\((\d+)\s*[–\-—]\s*(\d+)\s*(?:p|pen)',
                        chunk, re.I
                    )
                    if pm:
                        r["penalties"] = f"{pm.group(1)}-{pm.group(2)}"
                        r["winner"] = home if int(pm.group(1)) > int(pm.group(2)) else away
                    return r

    return None


def fetch_wikipedia():
    """Fetch match results from Wikipedia."""
    urls = [
        ("https://en.wikipedia.org/w/api.php?action=parse&page=2026_FIFA_World_Cup_knockout_stage&prop=text&format=json&origin=*",
         "knockout_stage"),
        ("https://en.wikipedia.org/w/api.php?action=parse&page=2026_FIFA_World_Cup&prop=text&format=json&origin=*",
         "main_page"),
    ]

    pages = {}
    for url, label in urls:
        try:
            text = fetch_page(url, label)
            if text:
                pages[label] = text
        except Exception as e:
            print(f"    Error: {e}", flush=True)

    if not pages:
        print("  No Wikipedia data fetched", flush=True)
        return []

    # Identify pending matches
    matches_file = DATA_DIR / 'matches.json'
    results_file = DATA_DIR / 'results.json'

    with open(matches_file, encoding="utf-8") as f:
        matches = json.load(f)

    existing = []
    if results_file.exists():
        with open(results_file, encoding="utf-8") as f:
            existing = json.load(f)

    completed_set = {(r['home'], r['away']) for r in existing}
    completed_set |= {(r['away'], r['home']) for r in existing}

    now = datetime.now(timezone(timedelta(hours=8)))

    pending = []
    for m in matches:
        if m.get('completed'):
            continue
        if (m['home_team'], m['away_team']) in completed_set:
            continue
        kbj = m.get('kickoff_bj', '')
        should_check = False
        if kbj:
            try:
                kickoff_dt = datetime.fromisoformat(kbj)
                if now > kickoff_dt + timedelta(hours=3):
                    should_check = True
            except Exception:
                pass  # Date parsing failure is expected for malformed kickoff data
        if not should_check:
            kdate = m.get('kickoff', '')[:10]
            yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')
            if kdate and kdate <= yesterday_str:
                should_check = True
        if should_check:
            pending.append(m)

    if not pending:
        print("  No pending matches to check", flush=True)
        return []

    names = [m['home_team'] + '/' + m['away_team'] for m in pending]
    print(f"  {len(pending)} pending: {names}", flush=True)

    # Search: try knockout page first (faster, more accurate), then main page
    results = []
    page_order = ['knockout_stage', 'main_page']

    for page_name in page_order:
        text = pages.get(page_name)
        if not text:
            continue
        still_pending = [m for m in pending
                         if not any(r['home'] == m['home_team'] and r['away'] == m['away_team']
                                    for r in results)]
        if not still_pending:
            break

        print(f"  Searching {page_name} ({len(still_pending)} remaining)...", flush=True)
        for m in still_pending:
            home, away = m['home_team'], m['away_team']
            try:
                # Timeout per match: 5 seconds
                signal.signal(signal.SIGALRM, _handler)
                signal.alarm(5)
                r = search_one_match(text, home, away, m)
                signal.alarm(0)
                if r:
                    results.append(r)
                    print(f"    ✓ {home} {r['home_goals']}-{r['away_goals']} {away} [{page_name}]", flush=True)
                else:
                    print(f"    ✗ {home} vs {away}: not in {page_name}", flush=True)
            except TimeoutError:
                signal.alarm(0)
                print(f"    ⚠ {home} vs {away}: timed out on {page_name}", flush=True)
            except Exception as e:
                print(f"    ⚠ {home} vs {away}: error: {e}", flush=True)

    return results


def save_results(new_results):
    """Save new results and update matches.json."""
    if not new_results:
        return 0

    existing = []
    results_file = DATA_DIR / 'results.json'
    if results_file.exists():
        with open(results_file, encoding="utf-8") as f:
            existing = json.load(f)

    added = 0
    for r in new_results:
        dup = any(
            (e['home'] == r['home'] and e['away'] == r['away']) or
            (e['home'] == r['away'] and e['away'] == r['home'])
            for e in existing
        )
        if not dup:
            existing.append(r)
            added += 1

    if added:
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        with open(DATA_DIR / "matches.json", encoding="utf-8") as f:
            matches = json.load(f)
        for m in matches:
            for r in new_results:
                if m['home_team'] == r['home'] and m['away_team'] == r['away']:
                    m['completed'] = True
                    m['home_goals'] = r.get('home_goals', 0)
                    m['away_goals'] = r.get('away_goals', 0)
        with open(DATA_DIR / 'matches.json', 'w', encoding='utf-8') as f:
            json.dump(matches, f, indent=2, ensure_ascii=False)

    # Update metadata
    with open(DATA_DIR / "last_refresh.txt", "w", encoding='utf-8') as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    results_count = len(existing)
    meta = {"last_wikipedia_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "results_count": results_count}
    with open(DATA_DIR / "meta.json", "w", encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"  Saved {added} new results (total: {results_count})")
    return added


if __name__ == '__main__':
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Refreshing data...")
    new = fetch_wikipedia()
    added = save_results(new)
    print(f"Found {len(new)}, added {added}")
    if added > 0:
        preds_file = DATA_DIR / 'predictions.json'
        if preds_file.exists():
            preds_file.unlink()
            print("  Cleared old predictions (will regenerate)")
        subprocess.run([sys.executable, str(BASE_DIR / 'build_static.py')], check=False, capture_output=True)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Refresh complete")
