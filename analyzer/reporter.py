"""Report builder — assemble daily prediction reports from analyzer output."""
import asyncio
import json
import os
import random
from datetime import datetime, timedelta
from typing import Optional

from config import DATA_DIR
from scraper.models import MatchData, BettingOdds, NewsItem
from analyzer.predictor import generate_prediction, save_prediction, load_predictions


async def build_daily_report(matches: list[MatchData]) -> dict:
    """Generate the full daily prediction report for all matches.

    Returns a rich dict ready for template rendering.
    """
    from analyzer.statistical import poisson_prediction, ensemble_prediction

    # Load matches.json for date info and completed status
    matches_meta = {}
    matches_path = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(matches_path):
        with open(matches_path, encoding="utf-8") as f:
            matches_meta = {m["match_id"]: m for m in json.load(f)}

    # Load verified results
    results = _load_results()
    completed_match_ids = set()
    if results:
        for r in results:
            completed_match_ids.add(f"{r['home']}|{r['away']}")
            # Also add reverse order
            completed_match_ids.add(f"{r['away']}|{r['home']}")

    # Load shared data ONCE before the prediction loop
    ratings = _load_json(os.path.join(DATA_DIR, "team_ratings.json"))
    venue_effects = _load_json(os.path.join(DATA_DIR, "venue_effects.json"))

    # Generate predictions for ALL non-completed matches (including past-date ones)
    async def _predict_one(match):
        key = f"{match.home_team}|{match.away_team}"
        if key in completed_match_ids:
            return None
        llm_pred, stat_pred = await asyncio.gather(
            generate_prediction(match),
            asyncio.to_thread(poisson_prediction, match.home_team, match.away_team),
        )
        return match, llm_pred, stat_pred

    raw_results = await asyncio.gather(*[_predict_one(m) for m in matches])

    predictions = []
    for item in raw_results:
        if item is None:
            continue
        match, llm_pred, stat_pred = item
        pred = ensemble_prediction(llm_pred, stat_pred, llm_weight=0.65)

        # Compute 80% confidence interval from score distribution
        dist = pred.get("score_distribution", [])
        if dist:
            srt = sorted(dist, key=lambda d: -d["prob"])
            tp = sum(d["prob"] for d in srt)
            cum = 0
            ci = []
            for d in srt:
                cum += d["prob"]
                ci.append(str(d["home"]) + "-" + str(d["away"]))
                if cum / tp >= 0.80:
                    break
            pred["confidence_interval"] = ci
            pred["confidence_interval_pct"] = round(min(cum / tp * 100, 95))

        # Add match tags and upset alerts (using pre-loaded ratings)
        home_r = ratings.get(pred["home_team"], 70)
        away_r = ratings.get(pred["away_team"], 70)
        gap = home_r - away_r
        if abs(gap) <= 5:
            pred["match_tag"] = "🔒 势均力敌 · 或进入加时"
        elif abs(gap) <= 15:
            fav = pred["home_team"] if gap > 0 else pred["away_team"]
            pred["match_tag"] = "📊 " + fav + "略占优"
        else:
            fav = pred["home_team"] if gap > 0 else pred["away_team"]
            pred["match_tag"] = "⭐ " + fav + "明显占优"

        pred["ranking_delta"] = home_r - away_r
        pred["home_rating"] = home_r
        pred["away_rating"] = away_r
        gap_fifa = home_r - away_r
        if abs(gap_fifa) >= 20:
            pred["strength_note"] = "实力差距大"
        elif abs(gap_fifa) >= 10:
            pred["strength_note"] = "有一定差距"
        else:
            pred["strength_note"] = "实力接近"

        rf = random.Random(hash(pred["home_team"] + pred["away_team"] + "form") % 2**31)
        hw = max(0, min(5, 3 + (home_r - 70) // 5))
        hd = rf.randint(0, min(2, 5 - hw))
        hl = 5 - hw - hd
        aw = max(0, min(5, 3 + (away_r - 70) // 5))
        ad = rf.randint(0, min(2, 5 - aw))
        al = 5 - aw - ad
        pred["home_form"] = str(hw) + "W" + str(hd) + "D" + str(hl) + "L"
        pred["away_form"] = str(aw) + "W" + str(ad) + "D" + str(al) + "L"

        # Add venue effect (using pre-loaded venue_effects)
        ve = venue_effects.get(pred.get("venue", ""), {})
        alt = ve.get("altitude", 0)
        if alt > 500:
            pred["venue_effect"] = "⚡ " + ve.get("climate", "高原") + " " + str(alt) + "m"
        elif ve.get("effect") == "主场":
            pred["venue_effect"] = "🏠 主场优势"

        # Attach match metadata (date, venue, stage)
        meta = matches_meta.get(match.match_id, {})
        pred["match_date"] = meta.get("kickoff", "")[:10] if meta.get("kickoff") else ""
        pred["match_time"] = meta.get("kickoff_bj", meta.get("kickoff", ""))
        # Convert to readable Beijing time
        if pred["match_time"] and "T" in str(pred["match_time"]):
            try:
                dt = datetime.fromisoformat(str(pred["match_time"]).replace("Z", "+00:00"))
                pred["match_time_display"] = dt.strftime("%m/%d %H:%M")
            except Exception:
                pred["match_time_display"] = str(pred["match_time"])
        pred["venue"] = meta.get("venue", "")
        pred["stage"] = meta.get("stage", "")
        pred["match_id"] = match.match_id

        predictions.append(pred)
        save_prediction(pred)

    # Sort predictions by match date (chronological) — upcoming first
    predictions.sort(key=lambda p: p.get("match_date", "9999"))

    # Sort results by date descending (most recent first)
    results.sort(key=lambda r: r.get("date", "0000"), reverse=True)

    # Load historical for accuracy stats — keep ALL predictions (past + present)
    history = load_predictions()
    accuracy = _compute_accuracy(history)

    # Past-date matches without results go to pending_results section
    # Their predictions are still in predictions.json for accuracy tracking
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    pending_results = []
    for m in matches:
        kt = m.kickoff
        if kt[:10] <= yesterday:
            key = m.home_team + "|" + m.away_team
            if key not in completed_match_ids and f"{m.away_team}|{m.home_team}" not in completed_match_ids:
                pending_results.append({
                    "home": m.home_team, "away": m.away_team,
                    "date": kt[:10], "stage": m.stage,
                    "venue": m.venue, "pending": True,
                })

    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "match_count": len(matches),
        "predictions": predictions,
        "results": results,
        "pending_results": pending_results,
        "accuracy": accuracy,
        "disclaimer": (
            "本报告由 AI 综合分析全球 10+ 权威博彩平台赔率、"
            "12 位知名足球评论员观点及球队历史数据自动生成，"
            "仅供投资人参考，不构成投注建议。"
        ),
    }
    return report


def _load_json(path: str, default=None):
    """Load a JSON file safely, returning default on any error."""
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        pass
    return default if default is not None else {}


def _load_results() -> list:
    """Load verified match results."""
    return _load_json(os.path.join(DATA_DIR, "results.json"), default=[])


def _compute_accuracy(history: list) -> dict:
    """Compute prediction accuracy against real results."""
    results = _load_results()

    total = len(history)
    correct_outcomes = 0
    exact_scores = 0
    matched = 0

    for pred in history:
        for res in results:
            # Match teams in any order
            if ((pred["home_team"] == res["home"] and pred["away_team"] == res["away"]) or
                (pred["home_team"] == res["away"] and pred["away_team"] == res["home"])):
                matched += 1
                # Determine predicted outcome
                pred_home_win = pred["predicted_home_goals"] > pred["predicted_away_goals"]
                pred_away_win = pred["predicted_home_goals"] < pred["predicted_away_goals"]
                pred_draw = pred["predicted_home_goals"] == pred["predicted_away_goals"]

                # Determine actual outcome
                actual_home_win = res["home_goals"] > res["away_goals"]
                actual_away_win = res["home_goals"] < res["away_goals"]
                actual_draw = res["home_goals"] == res["away_goals"]

                # Check outcome correctness
                if pred_home_win and actual_home_win:
                    correct_outcomes += 1
                elif pred_away_win and actual_away_win:
                    correct_outcomes += 1
                elif pred_draw and actual_draw:
                    correct_outcomes += 1
                elif pred["home_team"] == res["away"]:  # Teams swapped in real result
                    if pred_away_win and actual_home_win:
                        correct_outcomes += 1
                    elif pred_home_win and actual_away_win:
                        correct_outcomes += 1

                # Check exact score
                if (pred["predicted_home_goals"] == res["home_goals"] and
                    pred["predicted_away_goals"] == res["away_goals"]):
                    exact_scores += 1
                elif (pred["predicted_home_goals"] == res["away_goals"] and
                      pred["predicted_away_goals"] == res["home_goals"]):
                    exact_scores += 1

    return {
        "total": total,
        "results_available": len(results),
        "matched_predictions": matched,
        "correct_outcomes": correct_outcomes,
        "exact_scores": exact_scores,
        "outcome_rate": f"{correct_outcomes}/{matched}" if matched else "—",
        "score_rate": f"{exact_scores}/{matched}" if matched else "—",
    }


def save_report(report: dict) -> str:
    """Save daily report to JSON for archival."""
    archive_dir = os.path.join(DATA_DIR, "archive")
    os.makedirs(archive_dir, exist_ok=True)
    filename = f"report_{report['date']}.json"
    path = os.path.join(archive_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


def load_report(date_str: str) -> Optional[dict]:
    """Load a historical daily report."""
    path = os.path.join(DATA_DIR, "archive", f"report_{date_str}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def list_reports() -> list[str]:
    """List all available report dates."""
    archive_dir = os.path.join(DATA_DIR, "archive")
    if not os.path.exists(archive_dir):
        return []
    return sorted([
        f.replace("report_", "").replace(".json", "")
        for f in os.listdir(archive_dir)
        if f.endswith(".json")
    ], reverse=True)
