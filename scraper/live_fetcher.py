"""Live sports data fetcher — multi-source with fallback chain."""
import json
import os
import ssl
import urllib.request
from datetime import datetime
from config import DATA_DIR

# Map ESPN team names to our internal names
ESPN_NAME_MAP = {
    "Congo DR": "DR Congo",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Côte d'Ivoire": "Ivory Coast",
    "Ivory Coast": "Ivory Coast",
    "USA": "United States",
    "United States": "United States",
    "Korea Republic": "South Korea",
}


def _espn_name(name):
    return ESPN_NAME_MAP.get(name, name)


def fetch_espn_scoreboard(date_str=None):
    """Fetch match results from ESPN API for a given date (YYYYMMDD).

    Returns list of dicts: {home, away, home_goals, away_goals, status, date}
    Falls back to None on any error.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={date_str}"
    ctx = ssl.create_default_context()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        data = json.loads(resp.read().decode())
    except Exception:
        return None

    results = []
    for ev in data.get("events", []):
        comps = ev.get("competitions", [{}])
        status = ev.get("status", {}).get("type", {}).get("description", "")
        for comp in comps:
            competitors = comp.get("competitors", [])
            if len(competitors) >= 2:
                h = competitors[0]
                a = competitors[1]
                hs = h.get("score")
                aws = a.get("score")
                if hs is None or aws is None or hs == "?" or aws == "?":
                    continue
                results.append({
                    "home": _espn_name(h.get("team", {}).get("displayName", "")),
                    "away": _espn_name(a.get("team", {}).get("displayName", "")),
                    "home_goals": int(hs),
                    "away_goals": int(aws),
                    "status": status,
                    "date": ev.get("date", "")[:10],
                })
    return results


def fetch_wikipedia_knockout():
    """Fallback: fetch from Wikipedia knockout stage page."""
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(
            "https://en.wikipedia.org/w/api.php?action=parse&page=2026_FIFA_World_Cup_knockout_stage&prop=text&format=json&origin=*",
            headers={"User-Agent": "WorldCupPredict/2026"})
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        data = json.loads(resp.read().decode())
        return data.get("parse", {}).get("text", {}).get("*", "")
    except Exception:
        return None


def live_refresh_results():
    """Fetch latest results from ESPN + Wikipedia, merge into results.json.

    Returns (new_count, updated_count, total_results).
    """
    from datetime import datetime, timedelta

    results_path = os.path.join(DATA_DIR, "results.json")
    existing = []
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as f:
            existing = json.load(f)

    existing_keys = {(r["home"], r["away"]) for r in existing} | {(r["away"], r["home"]) for r in existing}

    new_count = [0]
    updated_count = [0]  # Lists for closure in merge functions

    # Fetch last 5 days from ESPN
    today = datetime.now()
    for days_ago in range(5):
        date_str = (today - timedelta(days=days_ago)).strftime("%Y%m%d")
        espn = fetch_espn_scoreboard(date_str)
        if espn:
            _merge_espn_results(espn, existing, existing_keys, new_count, updated_count)

    # Fallback: try FlashScore for any missing matches
    flashscore = _fetch_flashscore()
    if flashscore:
        _merge_flashscore_results(flashscore, existing, existing_keys, new_count, updated_count)

    # Fallback: try BBC Sport
    bbc = _fetch_bbc_sport()
    if bbc:
        _merge_bbc_results(bbc, existing, existing_keys, new_count, updated_count)

    if new_count[0] > 0 or updated_count[0] > 0:
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

    # Also update matches.json completed flags
    matches_path = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(matches_path):
        with open(matches_path, encoding="utf-8") as f:
            matches = json.load(f)
        for m in matches:
            key = (m["home_team"], m["away_team"])
            for r in existing:
                if (r["home"] == m["home_team"] and r["away"] == m["away_team"]):
                    m["completed"] = True
                    m["home_goals"] = r["home_goals"]
                    m["away_goals"] = r["away_goals"]
                    break
        with open(matches_path, "w", encoding="utf-8") as f:
            json.dump(matches, f, indent=2, ensure_ascii=False)

    return new_count[0], updated_count[0], len(existing)

def _merge_espn_results(espn, existing, existing_keys, new_count, updated_count):
    """Merge ESPN results into existing list in-place."""
    for r in espn:
        key = (r["home"], r["away"])
        if key in existing_keys or (r["away"], r["home"]) in existing_keys:
            for e in existing:
                if (e["home"] == r["home"] and e["away"] == r["away"]):
                    if e.get("home_goals") != r["home_goals"] or e.get("away_goals") != r["away_goals"]:
                        e["home_goals"] = r["home_goals"]
                        e["away_goals"] = r["away_goals"]
                        e["source"] = "ESPN"
                        updated_count[0] += 1
                    break
        elif r["status"] not in ("Full Time", "Final Score - After Extra Time", "Final Score - After Penalties"):
            pass
        elif r["home_goals"] == 0 and r["away_goals"] == 0 and "Extra" not in r.get("status", ""):
            pass
        else:
            r["stage"] = "32强淘汰赛"
            r["source"] = "ESPN"
            existing.append(r)
            existing_keys.add(key)
            existing_keys.add((r["away"], r["home"]))
            new_count[0] += 1


def _fetch_flashscore():
    """Try to scrape FlashScore for World Cup results."""
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(
            "https://www.flashscore.com/football/world/world-cup/results/",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        text = resp.read().decode("utf-8", errors="replace")
        return text
    except Exception:
        return None


def _merge_flashscore_results(html, existing, existing_keys, new_count, updated_count):
    """Parse FlashScore HTML for match results."""
    pass  # FlashScore uses JS rendering; HTML scraping not feasible without browser


def _fetch_bbc_sport():
    """Try BBC Sport for World Cup scores."""
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(
            "https://www.bbc.com/sport/football/world-cup/scores-fixtures",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _merge_bbc_results(html, existing, existing_keys, new_count, updated_count):
    """Parse BBC Sport HTML for match scores."""
    import re
    # Look for score patterns: team1 digits-digits team2
    pattern = re.compile(
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*?)\s+(\d+)\s*[-–—]\s*(\d+)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*?)',
        re.I)
    for m in pattern.finditer(html):
        home = m.group(1).strip()
        hg = int(m.group(2))
        ag = int(m.group(3))
        away = m.group(4).strip()
        if hg > 10 or ag > 10:
            continue
        if len(home) < 3 or len(away) < 3:
            continue
        # Map BBC names to our names
        home = _bbc_name(home)
        away = _bbc_name(away)
        key = (home, away)
        if key in existing_keys or (away, home) in existing_keys:
            for e in existing:
                if (e["home"] == home and e["away"] == away):
                    if e.get("home_goals") != hg or e.get("away_goals") != ag:
                        e["home_goals"] = hg
                        e["away_goals"] = ag
                        e["source"] = "BBC Sport"
                        updated_count[0] += 1
                    break
        else:
            existing.append({
                "home": home, "away": away,
                "home_goals": hg, "away_goals": ag,
                "stage": "32强淘汰赛", "source": "BBC Sport",
                "date": "",
            })
            existing_keys.add(key)
            existing_keys.add((away, home))
            new_count[0] += 1


def _bbc_name(name):
    """Map BBC name variations to our internal names."""
    mapping = {
        "Congo DR": "DR Congo", "Côte d'Ivoire": "Ivory Coast",
        "Ivory Coast": "Ivory Coast", "USA": "United States",
        "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    }
    return mapping.get(name, name)
